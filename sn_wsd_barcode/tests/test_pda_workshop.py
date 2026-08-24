"""PDA workshop scan routes: permission guard, one-scan OK pass and the
two-scan NG flow (SN first, defect code second)."""

import json

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestPdaWorkshopScan(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'PDA WS', 'code': 'PDAWS'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'PDA-L', 'code': 'PDAL', 'workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create(
            {'name': 'PDA-IN', 'code': 'PDALIN', 'x_station_type': 'assembly'})
        # single-operation route: the daily input IS the output operation
        # (valid per business -- e.g. one-station lines)
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'PDA-RT', 'code': 'PDART',
                'x_workshop_id': cls.workshop.id,
                'state': 'confirmed', 'x_production_side': 'single',
                'route_operation_ids': [
                    (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10,
                            'x_allow_entry': True, 'x_allow_exit': True}),
                ],
                'x_daily_input_operation_id': cls.op_in.id,
                'x_daily_output_operation_id': cls.op_in.id,
                'x_workorder_input_operation_id': cls.op_in.id,
            })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-PDA'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-PDA', 'default_code': 'DWG-PDA',
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'x_board_side': 'single'})
        cls.production = cls.env['mrp.production'].create({
            'product_id': cls.product.id, 'product_qty': 50,
            'company_id': cls.company.id})
        cls.order = cls.env['sn.wsd.mes.order'].create({
            'production_id': cls.production.id,
            'production_line_id': cls.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': 50})
        cls.order.action_online()
        cls.wc = cls.env['mrp.workcenter'].create({
            'name': 'PDA-WC', 'code': 'PDAWC',
            'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id,
            'x_operation_id': cls.op_in.id})
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'PDA Defect', 'code': 'PDAD',
            'category': 'other', 'severity': 'minor'})

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')

    def _rpc(self, path, params):
        response = self.url_open(
            path,
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                             'params': params}),
            headers={'Content-Type': 'application/json'},
        )
        return response.json().get('result', {})

    def _call(self, payload):
        return self._rpc('/sn_wsd_barcode/process_workshop_scan', payload)

    def test_01_ok_single_scan(self):
        res = self._call({
            'station_id': self.wc.id,
            'barcode': 'SN-PDA-001',
            'mode': 'ok',
        })
        self.assertTrue(res['ok'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-PDA-001')])
        self.assertEqual(history.result, 'ok')

    def test_02_ng_two_scans(self):
        first = self._call({
            'station_id': self.wc.id,
            'barcode': 'SN-PDA-002',
            'mode': 'ng',
        })
        self.assertTrue(first['ok'])
        self.assertTrue(first.get('pending_ng'))
        second = self._call({
            'station_id': self.wc.id,
            'barcode': 'PDAD',
            'mode': 'ng',
        })
        self.assertTrue(second['ok'])
        self.assertIn('PDAD', second['message'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-PDA-002')])
        self.assertEqual(history.result, 'ng')
        self.assertEqual(history.defect_code_id, self.defect)

    def test_03_group_guard(self):
        no_group = self.env['res.users'].create({
            'name': 'PDA No Group',
            'login': 'pda_nogroup',
            'email': 'pda_nogroup@example.com',
            'password': 'pda123',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.authenticate('pda_nogroup', 'pda123')
        res = self._call({
            'station_id': self.wc.id,
            'barcode': 'SN-PDA-003',
            'mode': 'ok',
        })
        self.assertFalse(res['ok'])
        self.assertIn('permission', res['message'].lower())
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-PDA-003')])
        self.assertFalse(history)
        # the smt loading context is guarded the same way
        res2 = self._rpc('/sn_wsd_barcode/smt/get_production_context',
                         {'workcenter_id': self.wc.id})
        self.assertFalse(res2['ok'])
