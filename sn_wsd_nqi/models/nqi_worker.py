"""NQI workers: birth queue drain, history backfill, asset enrichment,
test-result mapping and production progress.

Concurrency contract (design decision 7):
- single-flight via a transaction-level PostgreSQL advisory lock: it
  lives exactly as long as the run's transaction and is released by
  the database on commit or rollback, also when the transaction is
  aborted (a session-level lock would stay on the pooled connection);
- LIMIT-batched processing, resumable via max-id watermarks;
- keyset pagination (id > last), never OFFSET;
- no FOR UPDATE on business tables.

Failure containment: every tolerated failure runs through
``_nqi_guarded``, which flushes pending writes BEFORE opening its
savepoint. Odoo flushes again when the savepoint opens; a bad pending
write failing there would be swallowed by the guard and fail again on
the next statement of the transaction, outside any guard.
"""
import hashlib
import logging

from odoo import _, api, fields, models

from .nqi_generation import DATETIME_FORMAT, _enqueue_birth, _fmt

_logger = logging.getLogger(__name__)

LOCK_ENRICH = 'nqi_enrich'
LOCK_TESTS = 'nqi_test_results'
LOCK_QUEUE = 'nqi_birth_queue'
BIRTH_SOURCES = (
    'sn.wsd.serial.operation.history',
    'sn.wsd.serial.binding',
    'sn.wsd.meter.component.binding',
)
BATCH_SIZE = 500
QUEUE_MAX_FAILURES = 5


def _lock_hash(key):
    # process-stable 63-bit key: hash() is salted per process, so two
    # processes would otherwise never see each other's lock
    return int(hashlib.md5(key.encode()).hexdigest()[:15], 16)


def _nqi_to_text(value):
    """Mirror columns are text: flatten whatever a source yielded."""
    if value is None or value is False:
        return ''
    if isinstance(value, models.BaseModel):
        return value.display_name if value else ''
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return '%.10g' % value
    return str(value)


def _failed(result):
    return isinstance(result, Exception)


class NqiWorker(models.Model):
    _name = 'sn.wsd.nqi.worker'
    _description = 'NQI Generation Worker'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)

    # ----- single flight and failure containment -------------------------

    @api.model
    def _try_lock(self, key):
        """Single-flight guard for a worker run (see module docstring)."""
        self.env.cr.execute(
            'SELECT pg_try_advisory_xact_lock(%s)', (_lock_hash(key),))
        return self.env.cr.fetchone()[0]

    @api.model
    def _unlock(self, key):
        """Nothing to release: the lock ends with the transaction."""
        return True

    @api.model
    def _nqi_guarded(self, function, what):
        """Run ``function`` under a savepoint and tolerate a failure.

        Returns what ``function`` returned, or the exception it raised.
        """
        self.env.flush_all()
        try:
            with self.env.cr.savepoint():
                return function()
        except Exception as exc:  # noqa: BLE001 -- deliberate tolerance
            _logger.warning('NQI %s skipped: %s', what, exc)
            return exc

    # ----- UI helpers ---------------------------------------------------

    @api.model
    def _nqi_notify(self, message):
        """Notification action for the manual operations entries."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'NQI',
                'message': message,
                'sticky': True,
                'type': 'info',
            },
        }

    @api.model
    def action_backfill(self):
        """Manual entry: replay the whole source history through the
        queue (history that predates the module, failed enqueues)."""
        count = self.run_backfill()
        return _('Backfill: %(count)s events enqueued. %(result)s',
                 count=count, result=self.run_birth_queue())

    # ----- watermarks ----------------------------------------------------

    @api.model
    def _get_watermark(self, key):
        param = self.env['ir.config_parameter'].sudo()
        value = param.get_param('sn_wsd_nqi.watermark.%s' % key, '0')
        return int(value)

    @api.model
    def _set_watermark(self, key, value):
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('sn_wsd_nqi.watermark.%s' % key, str(value))

    # ----- birth queue ---------------------------------------------------

    @api.model
    def run_birth_queue(self, batch_size=BATCH_SIZE):
        """Dequeue birth events and run the (batched) birth functions.

        Drains the queue in batches; an event that keeps failing is
        dropped after QUEUE_MAX_FAILURES runs so it cannot block the
        queue (its anchor keeps any row a partial run already created).
        """
        if not self._try_lock(LOCK_QUEUE):
            return _('The birth queue is already being processed.')
        Queue = self.env['sn.wsd.nqi.birth.queue'].sudo()
        processed = dropped = 0
        last_id = 0
        while True:
            rows = Queue.search(
                [('id', '>', last_id)], order='id asc', limit=batch_size)
            if not rows:
                break
            # keyset: a failing event waits for the next run instead of
            # burning its retries inside this one
            last_id = max(rows.ids)
            for row in rows:
                done = self._nqi_guarded(
                    lambda row=row: self._process_and_drop(row),
                    'birth event %s (%s)' % (row.id, row.source_model))
                if _failed(done):
                    row.write({
                        'fail_count': row.fail_count + 1,
                        'error_text': str(done),
                    })
                    if row.fail_count >= QUEUE_MAX_FAILURES:
                        _logger.error(
                            'NQI birth event %s dropped after %d failures',
                            row.id, row.fail_count)
                        row.unlink()
                        dropped += 1
                else:
                    processed += 1
            if len(rows) < batch_size:
                break
        return _('Birth queue: %(processed)s processed, %(dropped)s dropped',
                 processed=processed, dropped=dropped)

    def _process_and_drop(self, row):
        self._process_birth_row(row)
        row.unlink()
        return True

    def _process_birth_row(self, row):
        if row.source_model not in self.env:
            raise ValueError('Unknown NQI source model %s'
                             % row.source_model)
        sources = self.env[row.source_model].sudo().browse(
            row.source_ids or []).exists()
        if row.source_model == 'sn.wsd.serial.operation.history':
            self.env['sn.wsd.nqi.fit.meter.info'].sudo(
            )._nqi_birth_from_history(sources)
            self.env['sn.wsd.nqi.fit.pcb.mounting'].sudo(
            )._nqi_birth_mounting(sources)
            self.env['sn.wsd.nqi.fit.meter.mounting'].sudo(
                )._nqi_birth_mounting(sources)
        elif row.source_model == 'sn.wsd.serial.binding':
            self.env['sn.wsd.nqi.fit.pcb.serial.bind'].sudo(
            )._nqi_birth_from_bindings(sources)
        elif row.source_model == 'sn.wsd.meter.component.binding':
            self.env['sn.wsd.nqi.fit.component.bind'].sudo(
                )._nqi_birth_from_component_bindings(sources)

    @api.model
    def run_backfill(self, source_models=None, from_id=0, to_id=None,
                     chunk=BATCH_SIZE):
        """Re-enqueue source events of an id window.

        Covers history that predates the module install and events whose
        enqueue failed. Idempotent: birth anchors collapse rows that
        already exist, so a window can be replayed at any time.
        """
        total = 0
        for model_name in source_models or BIRTH_SOURCES:
            Source = self.env[model_name].sudo()
            last = from_id
            while True:
                domain = [('id', '>', last)]
                if to_id:
                    domain.append(('id', '<=', to_id))
                batch = Source.search(domain, order='id asc', limit=chunk)
                if not batch:
                    break
                _enqueue_birth(
                    self.env.cr, self.env.uid,
                    batch[0].company_id.id, model_name, batch.ids)
                total += len(batch)
                last = max(batch.ids)
                if len(batch) < chunk:
                    break
        return total

    # ----- enrichment ----------------------------------------------------

    @api.model
    def run_enrich(self, batch_size=BATCH_SIZE):
        """Fill chain-derived columns on new asset rows that are still
        incomplete: nameplate barcode, test date/conclusion from the
        output pass, plan code when the row was born without one.

        Selection is by completeness, not by a single column: rows are
        born with the plan code already, and must still be enriched.
        """
        if not self._try_lock(LOCK_ENRICH):
            return _('Enrichment is already running.')
        Asset = self.env['sn.wsd.nqi.fit.meter.info'].sudo()
        last = self._get_watermark('asset')
        total = 0
        while True:
            rows = Asset.search(
                [('id', '>', last), ('missing_count', '>', 0),
                 ('push_state', '!=', 'pushed')],
                order='id asc', limit=batch_size)
            if not rows:
                break
            for row in rows:
                done = self._nqi_guarded(
                    lambda row=row: self._enrich_asset_row(row),
                    'enrichment of asset %s' % row.id)
                total += not _failed(done)
            last = max(rows.ids)
            if len(rows) < batch_size:
                break
        self._set_watermark('asset', last)
        return _('Enriched %(count)s asset rows', count=total)

    def _enrich_asset_row(self, row):
        record = row.operation_history_id.sudo()
        values = {}
        if record:
            sn = record.serial_identity_id
            # the nameplate mapping binds the nameplate SN *to* the
            # machine SN, so look the machine up on the bound side
            if sn and not row.barcode:
                binding = self.env['sn.wsd.serial.binding'].sudo().search([
                    ('bound_serial_identity_id', '=', sn.id),
                    ('binding_type', '=', 'nameplate'),
                ], order='is_current desc, binding_date desc, id desc',
                    limit=1)
                if binding:
                    values['barcode'] = binding.serial_identity_id.name
            if not row.test_date and record.out_date:
                values['test_date'] = record.out_date.strftime(
                    DATETIME_FORMAT.split(' ')[0])
            if not row.conc_code:
                values['conc_code'] = (
                    '1' if record.result == 'ok'
                    else '2' if record.result == 'ng' else '3')
        if not row.make_plan_no and record:
            plan_code = self._resolve_plan_code(record.mes_order_id)
            if plan_code:
                values['make_plan_no'] = plan_code
        if values:
            row.write(values)
        return True

    def _resolve_plan_code(self, mes_order, cache=None):
        """Plan code of the NQI plan a MES order feeds.

        MES order -> manufacturing order -> sales order line. Only an
        unambiguous line resolves (direct link, or a single-line order);
        the plan header's own code wins over the default "<order>-<n>".
        """
        production = mes_order.production_id
        if not production:
            return ''
        if cache is not None and production.id in cache:
            return cache[production.id]
        line = False
        if 'sale_line_id' in production._fields:
            line = production.sale_line_id
        if not line and production.origin:
            order = self.env['sale.order'].sudo().search(
                [('name', '=', production.origin)], limit=1)
            lines = order.order_line._nqi_product_lines()
            if len(lines) == 1:
                line = lines
        plan_code = ''
        if line:
            plan = self.env['sn.wsd.nqi.pt.plan'].sudo().search(
                [('sale_order_line_id', '=', line.id)], limit=1)
            plan_code = plan.plan_code if plan else (
                line._nqi_default_plan_code())
        if cache is not None:
            cache[production.id] = plan_code
        return plan_code

    # ----- test-result mapping engine ------------------------------------

    def _nqi_source_value(self, result, mapping):
        """Value a row-level mapping extracts from a test result."""
        kind = mapping.source_kind
        key = (mapping.source_key or '').strip()
        if kind == 'fixed':
            return key
        try:
            if kind == 'result_attr':
                if key == 'nqi_plan_code':
                    # NQI plan code of the MES order the result belongs to
                    return self._resolve_plan_code(result.mes_order_id)
                value = result
                for part in key.split('.'):
                    value = value[part]
                return value
            if kind == 'payload_key':
                value = result.payload
                for part in key.split('.'):
                    if not isinstance(value, dict):
                        return False
                    value = value.get(part)
                return value
        except (KeyError, TypeError):
            return False
        return False

    @api.model
    def _nqi_mapping_index(self):
        """Active mappings grouped as {model: {'detail': {...}, 'row': []}}.

        detail_project mappings drive the test points; the other source
        kinds (result attribute, payload key, fixed value) fill every
        row the model gets for a result.
        """
        index = {}
        for mapping in self.env['sn.wsd.nqi.field.mapping'].sudo().search(
                [('active', '=', True)]):
            model = mapping.nqi_model_id.model
            if not model:
                continue
            spec = index.setdefault(model, {'detail': {}, 'row': []})
            if mapping.source_kind == 'detail_project':
                spec['detail'].setdefault(mapping.source_key, []).append(
                    mapping)
            else:
                spec['row'].append(mapping)
        return index

    @api.model
    def run_test_mapping(self, batch_size=BATCH_SIZE, since_id=None):
        """Feed MES test results through the field mapping config into
        the testing mirror tables.

        Unmapped projects are skipped silently. ``since_id`` overrides
        the watermark so a historical window can be mapped again after
        configuring new mappings (rows are keyed by result and point).
        """
        if not self._try_lock(LOCK_TESTS):
            return _('Test mapping is already running.')
        index = self._nqi_mapping_index()
        if not index:
            return _('No active field mappings.')
        Result = self.env['sn.wsd.mes.test.result'].sudo()
        last = (self._get_watermark('tests')
                if since_id is None else since_id)
        created = scanned = 0
        while True:
            results = Result.search(
                [('id', '>', last)], order='id asc', limit=batch_size)
            if not results:
                break
            for result in results:
                created += self._map_test_result(result, index)
            scanned += len(results)
            last = max(results.ids)
            if len(results) < batch_size:
                break
        self._set_watermark('tests', last)
        return _('Mapped %(created)s rows from %(scanned)s results',
                 created=created, scanned=scanned)

    def _map_test_result(self, result, index):
        """Mirror rows of one test result, per configured target model.

        Point n merges the n-th occurrence of every mapped project of
        the result, so a 6-point test yields 6 rows numbered 1..6; the
        point number lands on the table's locator column. Models mapped
        from the result header only (no detail project) get one row per
        result.
        """
        created = 0
        sn = result.serial_identity_id
        if not sn:
            return 0
        details = result.detail_ids.sorted(
            key=lambda detail: (detail.sequence, detail.id))
        for model_name, spec in index.items():
            target = self.env[model_name].sudo()
            present = target._fields
            if 'test_result_id' not in present:
                _logger.warning(
                    'NQI mapping target %s is not a testing table: '
                    'skipped', model_name)
                continue
            points = {}
            for project, mappings in spec['detail'].items():
                occurrences = details.filtered(
                    lambda detail, name=project:
                    detail.project_name == name)
                for number, detail in enumerate(occurrences, start=1):
                    bucket = points.setdefault(number, {})
                    for mapping in mappings:
                        if mapping.nqi_field in present:
                            bucket[mapping.nqi_field] = (
                                detail.actual_value or '')
            # detail mappings drive the rows: a result without those
            # projects yields nothing. A model mapped from the result
            # header only gets exactly one row per result.
            if spec['detail']:
                point_count = max(points) if points else 0
            else:
                point_count = 1
            if not point_count:
                continue
            base = {
                'company_id': result.company_id.id,
                'test_result_id': result.id,
                'detect_date': _fmt(result.test_time),
            }
            if 'serial_no' in present:
                base['serial_no'] = sn.name
            elif 'pcb_code' in present:
                base['pcb_code'] = sn.name
            for mapping in spec['row']:
                if mapping.nqi_field in present:
                    base[mapping.nqi_field] = _nqi_to_text(
                        self._nqi_source_value(result, mapping))
            locator = next(
                (name for name in ('detect_item_point', 'para_index',
                                   'detect_item') if name in present), None)
            for number in range(1, point_count + 1):
                values = {name: value for name, value in base.items()
                          if name in present}
                values.update(points.get(number, {}))
                if locator and locator not in values:
                    values[locator] = str(number)
                domain = [('test_result_id', '=', result.id)]
                if locator:
                    domain.append((locator, '=', values.get(locator)))
                if target.search(domain, limit=1):
                    continue
                done = self._nqi_guarded(
                    lambda values=values: target.create(values),
                    'mapping row (%s)' % model_name)
                created += not _failed(done)
        return created

    # ----- production progress -------------------------------------------

    @api.model
    def run_progress(self):
        """Aggregate MES order quantities into PT_PRODUCTION_PROCESS.

        One row per NQI plan. Plan and finished quantities sum the MES
        orders of the plan's machine-kind product (every MES order of
        the chain when the plan sells no machine-kind product).
        """
        Process = self.env['sn.wsd.nqi.pt.process'].sudo()
        MesOrder = self.env['sn.wsd.mes.order'].sudo()
        plans = self.env['sn.wsd.nqi.pt.plan'].sudo().search([
            ('sale_order_line_id', '!=', False)])
        for plan in plans:
            line = plan.sale_order_line_id
            orders = MesOrder.search(
                [('production_id', 'in', plan._nqi_manufacturing_orders().ids),
                 ('state', '!=', 'cancelled')])
            if not orders:
                orders = MesOrder.search(
                    [('product_id', '=', line.product_id.id),
                     ('state', '!=', 'cancelled')])
            machine = orders.filtered(
                lambda order: order.product_id._nqi_product_kind()
                == 'machine')
            counted = machine or orders
            row = Process.search([
                ('company_id', '=', plan.company_id.id),
                ('plan_code', '=', plan.plan_code),
            ], limit=1)
            values = {
                'plan_num': str(int(sum(counted.mapped('planned_qty')))),
                'finish_num': str(int(sum(
                    counted.mapped('x_output_qty')))),
            }
            bidding = plan.bidding_ids[:1]
            if bidding.bidding_party_a:
                values.update({
                    'bidding_party_a_id': bidding.bidding_party_a_id.id,
                    'bidding_party_a': bidding.bidding_party_a,
                })
            if row:
                row.write(values)
            else:
                values.update({
                    'company_id': plan.company_id.id,
                    'plan_code': plan.plan_code,
                })
                self._nqi_guarded(
                    lambda values=values: Process.create(values),
                    'progress row (%s)' % plan.plan_code)
        return _('Progress rows updated for %(count)s plans',
                 count=len(plans))
