"""End-to-end flows on self-built data (no dependence on ambient rows):
plan expansion over the MTO chain, history backfill, asset enrichment,
the mapping engine, push retry, progress aggregation and queue health.
"""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from odoo import api
from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase

from odoo.addons.sn_wsd_nqi.models.nqi_generation import _fmt
from odoo.addons.sn_wsd_nqi.models.nqi_worker import _lock_hash

SEG_MACHINE = ('199999900001', '199999910000')
SEG_BOARD = ('299999900001', '299999910000')
SERVICES = {
    'rd': 'rdService', 'pr': 'prService', 'pt': 'ptService',
    'fit': 'ptService', 'mt': 'ptService', 'tt': 'ptService',
    'ot': 'ptService', 'sp': 'spService', 'et': 'etService',
    'pub': 'etService',
}


class TestNqiFullFlow(TransactionCase):

    def setUp(self):
        super().setUp()
        self.worker = self.env['sn.wsd.nqi.worker']
        config = self.env['sn.wsd.nqi.config'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        self.config = config or self.env['sn.wsd.nqi.config'].create({
            'company_id': self.env.company.id, 'enterprise_code': '88888'})

    # ----- builders ------------------------------------------------------

    def _product(self, code, kind):
        return self.env['product.template'].create({
            'name': code, 'default_code': code, 'nqi_product_kind': kind,
            'categ_id': self.env['product.category'].search(
                [], limit=1).id,
        }).product_variant_id

    def _sale_order(self, *products):
        order = self.env['sale.order'].create({
            'partner_id': self.env.ref('base.res_partner_2').id})
        lines = self.env['sale.order.line'].create([{
            'order_id': order.id, 'product_id': product.id,
        } for product in products])
        return order, lines

    def _mo(self, product, origin, line=None, qty=1000, segment=None):
        start, end = segment or SEG_MACHINE
        return self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': qty,
            'origin': origin,
            'sale_line_id': line.id if line else False,
            'x_sn_segment_start': start,
            'x_sn_segment_end': end,
        })

    def _identity(self, name):
        return self.env['sn.wsd.serial.identity'].create({
            'name': name, 'origin_type': 'manual'})

    def _mes_order(self, product_kind, production, exclude=None):
        """A real MES order pointed at the given MO and product kind."""
        domain = [('x_mes_route_id', '!=', False)]
        if exclude is not None:
            domain.append(('product_id', '!=', exclude.id))
        order = self.env['sn.wsd.mes.order'].search(domain, limit=1)
        order.product_id.product_tmpl_id.nqi_product_kind = product_kind
        # a released MES order refuses ORM edits: wiring the MO here is
        # fixture setup only, so it goes straight to the column
        self.env.cr.execute(
            'UPDATE sn_wsd_mes_order SET production_id = %s WHERE id = %s',
            (production.id, order.id))
        self.env.invalidate_all()
        return order

    def _history(self, order, sn, result='ok', at_output=True,
                 enqueue=True):
        operation = order.x_daily_output_operation_id
        if not at_output or not operation:
            operation = order.x_mes_route_id.operation_ids[:1]
        History = self.env['sn.wsd.serial.operation.history']
        if not enqueue:
            History = History.with_context(nqi_skip_birth=True)
        return History.create({
            'serial_identity_id': sn.id,
            'mes_order_id': order.id,
            'route_operation_id': operation.id,
            'result': result,
            'in_date': '2026-11-23 10:00:00',
            'out_date': '2026-11-23 10:01:00',
        })

    def _backfill(self, history):
        self.worker.run_backfill(
            source_models=['sn.wsd.serial.operation.history'],
            from_id=0, to_id=max(history.ids))

    # ----- plan expansion ------------------------------------------------

    def test_plan_header_per_line_and_detail_expansion(self):
        machine = self._product('NQI-T-METER', 'machine')
        board = self._product('NQI-T-BOARD', 'board')
        self.env['sn.wsd.nqi.rd.product.detail'].create({
            'product_id': machine.id,
            'product_detail_code': 'PD-METER',
            'product_detail_name': 'Meter detail',
        })
        bidding = self.env['sn.wsd.nqi.pr.bidding.info'].create({
            'business_contract_code': 'HT-2026-001'})
        order, lines = self._sale_order(machine)
        self._mo(machine, order.name, line=lines[0])
        board_mo = self._mo(board, order.name, segment=SEG_BOARD)

        # the form drives the bring-in: a single-product order picks
        # the line by itself, the header code is "<order>-<line position>"
        with Form(self.env['sn.wsd.nqi.pt.plan']) as form:
            form.sale_order_id = order
            self.assertEqual(form.sale_order_line_id, lines[0])
            self.assertEqual(form.plan_code, '%s-1' % order.name)
            self.assertEqual(form.product_code, 'PD-METER')
            form.bidding_ids.add(bidding)
            self.assertEqual(form.business_contract_code, 'HT-2026-001')
            plan = form.save()

        plan.action_expand_details()
        details = {detail.type: detail for detail in plan.detail_ids}
        self.assertEqual(set(details), {'01', '02'})
        self.assertEqual(details['01'].count, '1000')
        self.assertEqual(details['01'].start_serial_no, SEG_MACHINE[0])
        self.assertEqual(details['02'].finish_serial_no, SEG_BOARD[1])
        self.assertEqual(details['02'].plan_code, plan.plan_code)
        plan.action_expand_details()
        self.assertEqual(len(plan.detail_ids), 2)  # repeatable

        # a process row born under the chain carries the header's code
        mes_order = self._mes_order('board', board_mo)
        sn = self._identity('299999900777')
        history = self._history(mes_order, sn, at_output=False,
                                enqueue=False)
        self.env['sn.wsd.nqi.generation.mixin']._nqi_birth_mounting_rows(
            'sn.wsd.nqi.fit.pcb.mounting', history)
        rows = self.env['sn.wsd.nqi.fit.pcb.mounting'].search(
            [('operation_history_id', '=', history.id)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.make_plan_code, plan.plan_code)
        self.assertEqual(rows.pcb_code, '299999900777')

    def test_multi_line_order_keeps_line_plans_apart(self):
        meter_a = self._product('NQI-T-METER-A', 'machine')
        meter_b = self._product('NQI-T-METER-B', 'machine')
        order, lines = self._sale_order(meter_a, meter_b)
        mo_a = self._mo(meter_a, order.name, line=lines[0])
        mo_b = self._mo(meter_b, order.name, line=lines[1],
                        segment=('199999920001', '199999930000'))
        board_mo = self._mo(
            self._product('NQI-T-BOARD-B', 'board'), order.name,
            segment=SEG_BOARD)

        with Form(self.env['sn.wsd.nqi.pt.plan']) as form:
            form.sale_order_id = order
            # two product lines: the line is a deliberate choice
            self.assertFalse(form.sale_order_line_id)
            form.sale_order_line_id = lines[1]
            self.assertEqual(form.plan_code, '%s-2' % order.name)
            plan_b = form.save()
        plan_a = self.env['sn.wsd.nqi.pt.plan'].create({
            'sale_order_id': order.id,
            'sale_order_line_id': lines[0].id,
            'plan_code': '%s-1' % order.name,
        })
        plan_a.action_expand_details()
        plan_b.action_expand_details()
        self.assertEqual(
            plan_a._nqi_manufacturing_orders(), mo_a | board_mo)
        self.assertEqual(
            plan_b._nqi_manufacturing_orders(), mo_b | board_mo)
        self.assertEqual(len(plan_a.detail_ids), 2)
        self.assertEqual(len(plan_b.detail_ids), 2)

    def test_plan_expand_needs_a_line(self):
        meter_a = self._product('NQI-T-METER-C', 'machine')
        meter_b = self._product('NQI-T-METER-D', 'machine')
        order, _lines = self._sale_order(meter_a, meter_b)
        plan = self.env['sn.wsd.nqi.pt.plan'].create({
            'sale_order_id': order.id})
        with self.assertRaises(UserError):
            plan.action_expand_details()
        with self.assertRaises(UserError):
            self.env['sn.wsd.nqi.pt.plan'].create(
                {}).action_expand_details()

    # ----- backfill and enrichment ---------------------------------------

    def test_backfill_replays_history_without_duplicates(self):
        machine = self._product('NQI-T-METER-E', 'machine')
        order, lines = self._sale_order(machine)
        mo = self._mo(machine, order.name, line=lines[0])
        mes_order = self._mes_order('machine', mo)
        sn = self._identity('199999900888')
        # events that never reached the queue (they predate the module,
        # or their enqueue failed): created with the hook switched off
        self._history(mes_order, sn, enqueue=False)
        self._history(mes_order, sn, at_output=False, enqueue=False)
        history = self.env['sn.wsd.serial.operation.history'].search(
            [('serial_identity_id', '=', sn.id)])
        self.assertEqual(len(history), 2)
        Asset = self.env['sn.wsd.nqi.fit.meter.info']
        Process = self.env['sn.wsd.nqi.fit.meter.mounting']
        self.assertFalse(Asset.search([('serial_no', '=', sn.name)]))

        self._backfill(history)
        self.worker.run_birth_queue()
        self.assertEqual(len(Asset.search([('serial_no', '=', sn.name)])), 1)
        self.assertEqual(len(Process.search([('serial_no', '=', sn.name)])), 2)

        # replaying the window changes nothing
        self._backfill(history)
        self.worker.run_birth_queue()
        self.assertEqual(len(Asset.search([('serial_no', '=', sn.name)])), 1)
        self.assertEqual(len(Process.search([('serial_no', '=', sn.name)])), 2)

    def _asset_with_nameplate(self, tag, serial):
        machine = self._product('NQI-T-METER-%s' % tag, 'machine')
        order, lines = self._sale_order(machine)
        mo = self._mo(machine, order.name, line=lines[0])
        mes_order = self._mes_order('machine', mo)
        sn = self._identity(serial)
        nameplate = 'NP-%s-001' % tag
        # another nameplate bound to a different machine must not match
        self.env['sn.wsd.serial.binding'].create({
            'serial_identity_id': self._identity('NP-%s-OTHER' % tag).id,
            'bound_serial_identity_id': self._identity(
                serial[:-1] + '8').id,
            'binding_type': 'nameplate',
        })
        self.env['sn.wsd.serial.binding'].create({
            'serial_identity_id': self._identity(nameplate).id,
            'bound_serial_identity_id': sn.id,
            'binding_type': 'nameplate',
        })
        return mes_order, sn, nameplate, '%s-1' % order.name

    def test_enrich_fills_nameplate_barcode_and_chain_columns(self):
        mes_order, sn, nameplate, plan_code = self._asset_with_nameplate(
            'F', '199999900999')
        history = self._history(mes_order, sn, enqueue=False)
        self._backfill(history)
        self.worker.run_birth_queue()
        asset = self.env['sn.wsd.nqi.fit.meter.info'].search(
            [('serial_no', '=', sn.name)])
        self.assertEqual(len(asset), 1)
        # born with the plan code; barcode/date/conclusion still missing
        self.assertEqual(asset.make_plan_no, plan_code)
        self.assertTrue({'barcode', 'test_date', 'conc_code'}
                        & set(asset.missing_fields or []))

        self.worker.run_enrich()
        self.assertEqual(asset.barcode, nameplate)
        self.assertEqual(asset.test_date, '2026-11-23')
        self.assertEqual(asset.conc_code, '1')
        self.assertFalse(asset.missing_count)

    def test_auto_fill_action_reports_and_skips_pushed(self):
        mes_order, sn, nameplate, _plan_code = self._asset_with_nameplate(
            'G', '199999900901')
        history = self._history(mes_order, sn, enqueue=False)
        self.env['sn.wsd.nqi.fit.meter.info'].create({
            'serial_no': sn.name, 'operation_history_id': history.id,
            'status': '1'})
        asset = self.env['sn.wsd.nqi.fit.meter.info'].search(
            [('serial_no', '=', sn.name)])
        action = asset.action_try_auto_fill()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertIn('1 of 1', action['params']['message'])
        self.assertEqual(asset.barcode, nameplate)
        asset.write({'push_state': 'pushed'})
        # pushed rows are frozen: the action leaves them alone
        action = asset.action_try_auto_fill()
        self.assertIn('0 of 0', action['params']['message'])

    # ----- mapping engine -------------------------------------------------

    def _test_result(self, sn, details, **extra):
        result = self.env['sn.wsd.mes.test.result'].create(dict({
            'serial_identity_id': sn.id,
        }, **extra))
        self.env['sn.wsd.mes.test.result.detail'].create([{
            'test_result_id': result.id,
            'sequence': sequence,
            'project_name': project,
            'actual_value': value,
            'result': 'ok',
        } for sequence, project, value in details])
        return result

    def _mapping(self, model, field, kind, key):
        """A mapping is unique per company: reuse one the database
        already holds (the full data set carries demo mappings)."""
        Mapping = self.env['sn.wsd.nqi.field.mapping']
        existing = Mapping.search([
            ('nqi_model_id.model', '=', model), ('nqi_field', '=', field),
            ('source_kind', '=', kind), ('source_key', '=', key)], limit=1)
        if existing:
            return existing
        return Mapping.create({
            'nqi_model_id': self.env['ir.model']._get_id(model),
            'nqi_field': field,
            'source_kind': kind,
            'source_key': key,
        })

    def test_mapping_engine_points_and_row_sources(self):
        Basic = self.env['sn.wsd.nqi.mt.basicerr']
        self._mapping('sn.wsd.nqi.mt.basicerr', 'error',
                      'detail_project', 'ERROR')
        self._mapping('sn.wsd.nqi.mt.basicerr', 'load_current',
                      'detail_project', 'LOAD_CURRENT')
        self._mapping('sn.wsd.nqi.mt.basicerr', 'ave_err',
                      'result_attr', 'basic_error')
        self._mapping('sn.wsd.nqi.mt.basicerr', 'conc_code', 'fixed', '1')
        self._mapping('sn.wsd.nqi.mt.basicerr', 'detect_circle',
                      'payload_key', 'test.circle')
        self._mapping('sn.wsd.nqi.mt.basicerr', 'err_up',
                      'result_attr', 'no_such_column')
        sn = self._identity('199999910001')
        details = []
        for point in range(1, 7):
            details.append((point, 'ERROR', '0.%d' % point))
            details.append((point, 'LOAD_CURRENT', '%dA' % point))
        # a project nobody mapped must not create anything
        details.append((1, 'UNMAPPED', 'x'))
        result = self._test_result(
            sn, details, payload={'test': {'circle': 5}}, basic_error=0.125)
        self._test_result(self._identity('199999910009'),
                          [(1, 'SOMETHING_ELSE', 'x')])

        self.worker.run_test_mapping()
        rows = Basic.search([('serial_no', '=', sn.name)],
                            order='detect_item_point')
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows.mapped('detect_item_point'),
                         ['1', '2', '3', '4', '5', '6'])
        self.assertEqual(rows[2].error, '0.3')
        self.assertEqual(rows[2].load_current, '3A')
        for row in rows:
            self.assertEqual(row.ave_err, '0.125')
            self.assertEqual(row.conc_code, '1')
            self.assertEqual(row.detect_circle, '5')
            self.assertFalse(row.err_up)  # dead source: left empty
            self.assertEqual(row.detect_date, _fmt(result.test_time))
            self.assertEqual(row.serial_no, sn.name)
        # a result without the mapped projects yields no row
        self.assertFalse(Basic.search([('serial_no', '=', '199999910009')]))

        # re-running the same window adds nothing
        self.worker.run_test_mapping(since_id=0)
        self.assertEqual(len(Basic.search([('serial_no', '=', sn.name)])), 6)

    def test_mapping_engine_header_only_target(self):
        self._mapping('sn.wsd.nqi.mt.mounting', 'test_result',
                      'result_attr', 'result')
        sn = self._identity('199999910002')
        result = self._test_result(sn, [(1, 'ANYTHING', 'x')])
        rows = self.env['sn.wsd.nqi.mt.mounting']
        self.assertFalse(rows.search([('test_result_id', '=', result.id)]))
        self.worker.run_test_mapping()
        rows = rows.search([('test_result_id', '=', result.id)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.test_result, 'ok')

    def test_guard_tolerates_one_bad_row_and_keeps_the_transaction(self):
        """A row the database refuses is skipped; the worker goes on
        and the transaction stays usable."""
        basic = 'sn.wsd.nqi.mt.basicerr'
        # a mapping wired to a non-text column: the row of the point
        # that carries that project cannot be inserted
        self._mapping(basic, 'company_id', 'detail_project', 'BROKEN')
        sn = self._identity('199999910003')
        result = self._test_result(sn, [
            (1, 'ERROR', '0.1'), (2, 'ERROR', '0.2'), (3, 'ERROR', '0.3')])
        self.env['sn.wsd.mes.test.result.detail'].create([{
            'test_result_id': result.id, 'sequence': sequence,
            'project_name': 'BROKEN', 'actual_value': value,
            'result': 'ok'}
            for sequence, value in ((1, '1'), (2, 'not-a-company'), (3, '1'))])
        self.worker.run_test_mapping()
        rows = self.env[basic].search(
            [('test_result_id', '=', result.id)], order='detect_item_point')
        self.assertEqual(rows.mapped('detect_item_point'), ['1', '3'])
        # the transaction is still healthy
        self.env[basic].flush_recordset(['detect_item_point'])

    def test_bad_pending_write_surfaces_once_instead_of_poisoning(self):
        """A write that is still pending when the worker starts and
        turns out invalid must fail where it is flushed - not be
        swallowed by a guard and re-raised on every later statement."""
        from psycopg2.errors import InFailedSqlTransaction
        basic = 'sn.wsd.nqi.mt.basicerr'
        self._mapping(basic, 'error', 'detail_project', 'ERROR')
        duplicate = self._mapping(basic, 'error', 'detail_project', 'ERR_X')
        sn = self._identity('199999910004')
        self._test_result(sn, [(1, 'ERROR', '0.1')])
        # deferred write: the unique key only bites when it is flushed
        duplicate.write({'source_key': 'ERROR'})
        caught = None
        try:
            self.worker.run_test_mapping()
        except Exception as exc:  # noqa: BLE001 -- the point of the test
            caught = exc
        self.assertIsNotNone(caught)
        self.assertNotIsInstance(caught, InFailedSqlTransaction)

    # ----- push retry ------------------------------------------------------

    def _gateway(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                received.append(json.loads(self.rfile.read(length)))
                body = json.dumps(
                    {'return_flag': '1', 'return_msg': 'ok'}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(
            target=server.serve_forever, daemon=True).start()
        return server, received

    def test_failed_batch_can_be_retried(self):
        row = self.env['sn.wsd.nqi.rd.product.info'].create({
            'product_code': 'NQI-T-RETRY',
            'product_type': 'T',
            'product_name': 'Retry',
            'product_categid': '101',
            'product_design_basis': 'GB',
        })
        row.action_mark_to_push()
        # nothing listens on port 9: the first attempt fails
        self.config.write({
            'api_base_url': 'http://127.0.0.1:9', 'timeout_sec': 5})
        self.worker.run_push('sn.wsd.nqi.rd.product.info')
        self.assertEqual(row.push_state, 'failed')
        log = self.env['sn.wsd.nqi.push.log'].search(
            [('model_name', '=', row._name)], limit=1)
        self.assertEqual(log.state, 'failed')
        self.assertTrue(log.error_text)

        server, received = self._gateway()
        try:
            self.config.api_base_url = 'http://127.0.0.1:%d' % (
                server.server_port)
            log.action_retry()
        finally:
            server.shutdown()
        self.assertEqual(row.push_state, 'pushed')
        self.assertEqual(row.notice_no, log.notice_no)
        self.assertEqual(log.state, 'success')
        self.assertEqual(log.retry_count, 1)
        self.assertEqual(len(received), 1)
        records = received[0]['data'][0]['recond']
        self.assertIn('NQI-T-RETRY',
                      [record['PRODUCT_CODE'] for record in records])

    def test_run_push_all_covers_every_waiting_model(self):
        asset_model = 'sn.wsd.nqi.rd.product.info'
        detail_model = 'sn.wsd.nqi.pt.plan.detail'
        product = self.env[asset_model].create({
            'product_code': 'NQI-T-ALL-1',
            'product_type': 'T',
            'product_name': 'All',
            'product_categid': '101',
            'product_design_basis': 'GB',
        })
        product.action_mark_to_push()
        # a pushed row and a draft row of other models must stay untouched
        detail = self.env[detail_model].create({
            'plan_code': 'NQI-T-ALL-PLAN', 'count': '5', 'type': '01',
            'start_serial_no': '199999950001',
            'finish_serial_no': '199999950005'})
        detail.action_mark_to_push()
        frozen = self.env[detail_model].create({
            'plan_code': 'NQI-T-ALL-PLAN', 'count': '1', 'type': '01',
            'start_serial_no': '199999950009',
            'finish_serial_no': '199999950009',
            'push_state': 'pushed'})
        server, received = self._gateway()
        try:
            self.config.api_base_url = 'http://127.0.0.1:%d' % (
                server.server_port)
            message = self.worker.run_push_all()
        finally:
            server.shutdown()
        self.assertEqual(product.push_state, 'pushed')
        self.assertEqual(detail.push_state, 'pushed')
        self.assertEqual(frozen.push_state, 'pushed')
        self.assertIn('RD_PRODUCT_INFO: 1', message)
        self.assertIn('PT_PRODUCTION_DETAIL_PLAN: 1', message)
        self.assertNotIn('left for the next run', message)
        services = sorted(body['serviceName'] for body in received)
        self.assertEqual(services, ['ptService', 'rdService'])
        self.assertEqual(self.worker.run_push_all(), 'Nothing to push.')

    # ----- table names, locks, queue health, progress ---------------------

    def test_every_mirror_model_maps_to_one_distinct_table(self):
        transport = self.env['sn.wsd.nqi.transport']
        tables = {}
        for model_name in sorted(self.env.registry.models):
            if not model_name.startswith('sn.wsd.nqi.'):
                continue
            model = self.env[model_name]
            if model._abstract or 'push_state' not in model._fields:
                continue
            table = transport._table_for(model_name)
            self.assertEqual(table, table.upper())
            self.assertNotIn(table, tables, '%s and %s share %s' % (
                tables.get(table), model_name, table))
            tables[table] = model_name
            group = model_name.split('.')[3]
            if group in ('mt', 'tt', 'ot'):
                self.assertTrue(table.endswith('_CONC'), model_name)
            else:
                self.assertFalse(table.endswith('_CONC'), model_name)
            self.assertEqual(transport._service_for(model_name),
                             SERVICES[group])
        self.assertEqual(len(tables), 73)
        self.assertEqual(
            transport._table_for('sn.wsd.nqi.sp.recall'), 'SP_METER_RECALL')

    def test_advisory_lock_key_is_process_stable(self):
        # hash() is salted per process; the key must come from a stable
        # digest so a shell run and a cron run exclude each other
        for key in ('nqi_enrich', 'nqi_test_results', 'birth'):
            expected = int(hashlib.md5(key.encode()).hexdigest()[:15], 16)
            self.assertEqual(_lock_hash(key), expected)
            self.assertLess(_lock_hash(key), 2 ** 63)

    def test_queue_drops_an_event_that_keeps_failing(self):
        Queue = self.env['sn.wsd.nqi.birth.queue']
        row = Queue.create({
            'source_model': 'no.such.model', 'source_ids': [1],
            'fail_count': 4})
        message = self.worker.run_birth_queue()
        self.assertEqual(message, 'Birth queue: 0 processed, 1 dropped')
        self.assertFalse(row.exists())
        self.assertFalse(Queue.search([]))

    def test_progress_sums_the_plan_machine_orders(self):
        meter = self._product('NQI-T-METER-H', 'machine')
        board = self._product('NQI-T-BOARD-H', 'board')
        order, lines = self._sale_order(meter)
        mo_meter = self._mo(meter, order.name, line=lines[0])
        mo_board = self._mo(board, order.name, segment=SEG_BOARD)
        meter_order = self._mes_order('machine', mo_meter)
        board_order = self._mes_order('board', mo_board,
                                      exclude=meter_order.product_id)
        plan = self.env['sn.wsd.nqi.pt.plan'].create({
            'sale_order_id': order.id,
            'sale_order_line_id': lines[0].id,
            'plan_code': '%s-1' % order.name,
        })
        self.worker.run_progress()
        self.worker.run_progress()  # upsert: still a single row
        rows = self.env['sn.wsd.nqi.pt.process'].search(
            [('plan_code', '=', plan.plan_code)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.plan_num, str(int(meter_order.planned_qty)))
        self.assertEqual(
            rows.finish_num, str(int(meter_order.x_output_qty)))
