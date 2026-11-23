from odoo.tests import TransactionCase


class TestNqiGeneration(TransactionCase):
    """Birth hooks: tolerant, idempotent, correct axis routing."""

    def _mes_order(self):
        return self.env['sn.wsd.mes.order'].search([
            ('x_mes_route_id', '!=', False),
            ('product_id', '!=', False),
        ], limit=1) or None

    def _identity(self, name):
        return self.env['sn.wsd.serial.identity'].create({
            'name': name,
            'origin_type': 'manual',
        })

    def _history(self, order, sn, result='ok', output=True):
        operation = order.x_daily_output_operation_id
        if not output or not operation:
            operation = order.x_mes_route_id.operation_ids[:1]
        return self.env['sn.wsd.serial.operation.history'].create({
            'serial_identity_id': sn.id,
            'mes_order_id': order.id,
            'route_operation_id': operation.id,
            'result': result,
            'in_date': '2026-11-23 10:00:00',
            'out_date': '2026-11-23 10:01:00',
        })

    def test_output_pass_births_asset_once(self):
        order = self._mes_order()
        if not order or not order.x_daily_output_operation_id:
            self.skipTest('needs a MES order with route and output op')
        order.product_id.product_tmpl_id.nqi_product_kind = 'machine'
        sn = self._identity('126110003901')
        self._history(order, sn)
        self._history(order, sn)  # replay: different event, same SN
        assets = self.env['sn.wsd.nqi.fit.meter.info'].search([
            ('serial_no', '=', '126110003901')])
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets.status, '1')

    def test_mounting_rows_follow_product_axis(self):
        order = self._mes_order()
        if not order:
            self.skipTest('needs a MES order')
        order.product_id.product_tmpl_id.nqi_product_kind = 'board'
        sn = self._identity('226110003902')
        self._history(order, sn, output=False)
        board_rows = self.env['sn.wsd.nqi.fit.pcb.mounting'].search([
            ('pcb_code', '=', '226110003902')])
        machine_rows = self.env['sn.wsd.nqi.fit.meter.mounting'].search([
            ('serial_no', '=', '226110003902')])
        self.assertEqual(len(board_rows), 1)
        self.assertEqual(len(machine_rows), 0)

    def test_binding_births_bridge_row(self):
        board_sn = self._identity('226110003903')
        machine_sn = self._identity('126110003903')
        self.env['sn.wsd.serial.binding'].create({
            'serial_identity_id': board_sn.id,
            'bound_serial_identity_id': machine_sn.id,
            'binding_type': 'machine',
        })
        bridges = self.env['sn.wsd.nqi.fit.pcb.serial.bind'].search([
            ('serial_no', '=', '126110003903'),
            ('pcb_code', '=', '226110003903')])
        self.assertEqual(len(bridges), 1)
        self.assertTrue(bridges.binding_id)
