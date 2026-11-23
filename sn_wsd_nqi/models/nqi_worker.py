"""NQI enrich worker: watermark cron over mirror rows and test results.

Concurrency contract (design decision 7):
- single-flight via PostgreSQL advisory locks (cron vs manual button);
- LIMIT-batched short transactions, resumable via max-id watermarks;
- keyset pagination (id > last), never OFFSET;
- no FOR UPDATE on business tables.
"""
import logging

from odoo import api, fields, models

from .nqi_generation import DATETIME_FORMAT, _fmt

_logger = logging.getLogger(__name__)

LOCK_KEY_ENRICH = 'nqi_enrich'
LOCK_KEY_TESTS = 'nqi_test_results'
BATCH_SIZE = 500


def _lock_hash(key):
    # stable 64-bit hash for pg advisory locks
    return hash(key) & 0x7FFFFFFFFFFFFFFF


class NqiWorker(models.Model):
    _name = 'sn.wsd.nqi.worker'
    _description = 'NQI Generation Worker'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)

    # ----- single-flight -------------------------------------------------

    @api.model
    def _try_lock(self, key):
        self.env.cr.execute(
            'SELECT pg_try_advisory_lock(%s)', (_lock_hash(key),))
        return self.env.cr.fetchone()[0]

    @api.model
    def _unlock(self, key):
        self.env.cr.execute(
            'SELECT pg_advisory_unlock(%s)', (_lock_hash(key),))

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

    @api.model
    def run_birth_queue(self, batch_size=500):
        """Dequeue birth events and run the (batched) birth functions."""
        if not self._try_lock('nqi_birth_queue'):
            return 'birth queue already running'
        try:
            Queue = self.env['sn.wsd.nqi.birth.queue'].sudo()
            rows = Queue.search([], order='id asc', limit=batch_size)
            for row in rows:
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
                row.unlink()
            return 'birth queue processed %d events' % len(rows)
        finally:
            self._unlock('nqi_birth_queue')

    # ----- enrichment ----------------------------------------------------

    @api.model
    def run_enrich(self, batch_size=BATCH_SIZE):
        """Fill chain-derived columns on born asset rows (plan code,
        barcode via nameplate mapping, test date/conclusion from the
        output pass)."""
        if not self._try_lock(LOCK_KEY_ENRICH):
            return 'enrich already running'
        try:
            Asset = self.env['sn.wsd.nqi.fit.meter.info'].sudo()
            domain = [
                ('id', '>', self._get_watermark('asset')),
                ('make_plan_no', '=', False),
            ]
            rows = Asset.search(domain, order='id asc', limit=batch_size)
            for row in rows:
                self._enrich_asset_row(row)
            if rows:
                self._set_watermark('asset', max(rows.ids))
            return 'enriched %d' % len(rows)
        finally:
            self._unlock(LOCK_KEY_ENRICH)

    def _enrich_asset_row(self, row):
        history = self.env['sn.wsd.serial.operation.history'].sudo().browse(
            row.operation_history_id.id)
        record = history.exists() and history or None
        values = {}
        if record:
            sn = record.serial_identity_id
            # nameplate barcode via the SN binding chain
            if sn:
                binding = self.env['sn.wsd.serial.binding'].sudo().search([
                    ('serial_identity_id', '=', sn.id),
                    ('binding_type', '=', 'nameplate'),
                ], order='binding_date desc', limit=1)
                if binding and not row.barcode:
                    values['barcode'] = binding.serial_identity_id.name
            if not row.test_date and record.out_date:
                values['test_date'] = record.out_date.strftime(
                    DATETIME_FORMAT.split(' ')[0])
            if not row.conc_code:
                values['conc_code'] = (
                    '1' if record.result == 'ok'
                    else '2' if record.result == 'ng' else '3')
        order = record and record.mes_order_id or None
        if order and not row.make_plan_no:
            # plan code resolution: MES order -> MO -> sales order name
            plan_code = self._resolve_plan_code(order)
            if plan_code:
                values['make_plan_no'] = plan_code
        if values:
            row.write(values)

    @api.model
    def _resolve_plan_code(self, mes_order):
        """MES order -> manufacturing order -> sales order name."""
        production = mes_order.production_id
        if not production:
            return ''
        sale = self.env['sale.order'].sudo()
        if production.procurement_group_id:
            order = sale.search(
                [('procurement_group_id', '=',
                  production.procurement_group_id.id)], limit=1)
            if order:
                return order.name
        if production.origin:
            order = sale.search(
                [('name', '=', production.origin)], limit=1)
            if order:
                return order.name
        return production.origin or ''

    # ----- test-result mapping engine ------------------------------------

    @api.model
    def run_test_mapping(self, batch_size=BATCH_SIZE):
        """Feed MES test results through the field mapping config into
        the 31 testing mirror tables. Unmapped project names are
        skipped silently - configure the mapping and re-run."""
        if not self._try_lock(LOCK_KEY_TESTS):
            return 'test mapping already running'
        try:
            mappings = self.env['sn.wsd.nqi.field.mapping'].sudo().search([
                ('active', '=', True),
                ('source_kind', '=', 'detail_project'),
            ])
            if not mappings:
                return 'no active mappings'
            by_project = {}
            for mapping in mappings:
                by_project.setdefault(mapping.source_key, []).append(mapping)
            Result = self.env['sn.wsd.mes.test.result'].sudo()
            watermark = self._get_watermark('tests')
            results = Result.search(
                [('id', '>', watermark)], order='id asc', limit=batch_size)
            created = 0
            for result in results:
                created += self._map_test_result(result, by_project)
            if results:
                self._set_watermark('tests', max(results.ids))
            return 'mapped %d rows from %d results' % (created, len(results))
        finally:
            self._unlock(LOCK_KEY_TESTS)

    @api.model
    def _map_test_result(self, result, by_project):
        helpers = self.env['sn.wsd.nqi.generation.mixin']
        created = 0
        sn = result.serial_identity_id
        if not sn:
            return 0
        base = {
            'company_id': result.company_id.id,
            'test_result_id': result.id,
            'serial_no': sn.name,
            'detect_date': _fmt(result.test_time),
        }
        for detail in result.detail_ids:
            for mapping in by_project.get(detail.project_name, []):
                target = mapping.nqi_model_id.model
                if not target or not mapping.nqi_field:
                    continue
                row_model = self.env[target].sudo()
                if mapping.nqi_field not in row_model._fields:
                    continue
                existing = row_model.search(
                    [('test_result_id', '=', result.id),
                     (mapping.nqi_field, '=', detail.actual_value or '')],
                    limit=1)
                if existing:
                    continue
                values = dict(base)
                values[mapping.nqi_field] = detail.actual_value or ''
                try:
                    with self.env.cr.savepoint():
                        row_model.create(values)
                    created += 1
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        'NQI mapping row skipped (%s): %s', target, exc)
        return created

    # ----- production progress -------------------------------------------

    @api.model
    def run_progress(self):
        """Aggregate MES order progress into PT_PRODUCTION_PROCESS rows.

        One row per plan task (plan code resolved through the MO chain);
        upsert by (company, plan_code): plan quantity from the MES order,
        finished quantity from its output count.
        """
        Process = self.env['sn.wsd.nqi.pt.process'].sudo()
        orders = self.env['sn.wsd.mes.order'].sudo().search([
            ('state', '!=', 'cancelled'),
        ])
        for order in orders:
            plan_code = self._resolve_plan_code(order)
            if not plan_code:
                continue
            row = Process.search([
                ('company_id', '=', order.company_id.id),
                ('plan_code', '=', plan_code),
            ], limit=1)
            values = {
                'plan_num': str(int(order.planned_qty or 0)),
                'finish_num': str(int(order.x_output_qty or 0)),
            }
            if row:
                row.write(values)
            else:
                row_values = dict(
                    values, company_id=order.company_id.id,
                    plan_code=plan_code)
                try:
                    with self.env.cr.savepoint():
                        Process.create(row_values)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        'NQI progress row skipped for %s: %s',
                        plan_code, exc)
        return 'progress rows updated for %d orders' % len(orders)
