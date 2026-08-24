from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.sn_wsd_mrp.models.mes_order import MesOrder


@tagged('post_install', '-at_install')
class TestRepair(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def _get_or_create(model, code_key, code, name, **kw):
            existing = cls.env[model].search([(code_key, '=', code)], limit=1)
            return existing or cls.env[model].create({code_key: code, 'name': name, **kw})

        # Reuse a matching dictionary row when the E2E data already created one.
        cls.failure_cause = _get_or_create('sn.wsd.repair.cause', 'code', 'C01', 'Cold Solder Joint')
        cls.defect_code = _get_or_create('sn.wsd.quality.defect.code', 'code', 'D01', 'Solder Defect')
        cls.scrap_reason = _get_or_create('sn.wsd.scrap.reason', 'code', 'SCR01', 'Unrepairable Board', category='other')
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'REPAIR TEST WS'})
        cls.production_line = cls.env['sn.mrp.production.line'].create({
            'name': 'REPAIR TEST LINE',
            'workshop_id': cls.workshop.id,
            'company_id': cls.env.company.id,
        })
        cls.production = cls.env['mrp.production'].create({
            'product_id': cls.env['product.product'].create({'name': 'Repair Board'}).id,
            'product_qty': 10,
        })
        cls.mes_order = cls._create_mes_order(cls.production, 10)
        cls.route_operation = cls.mes_order.x_route_operation_ids[0] if cls.mes_order.x_route_operation_ids else False
        cls.serial = cls.env['sn.wsd.serial.identity'].create({
            'name': 'RP-SN-001',
            'company_id': cls.env.company.id,
        })
        cls.env['sn.wsd.serial.wip'].create({
            'serial_identity_id': cls.serial.id,
            'mes_order_id': cls.mes_order.id,
            'route_operation_id': cls.route_operation.id,
        })

    @classmethod
    def _create_mes_order(cls, production, qty):
        # Materialize a minimal single-operation private route: repair tests
        # need real MES order operations, not the full released-route setup.
        def _fake_setup_route(self):
            if self.x_route_operation_ids:
                return True
            route = self.env['sn.wsd.mes.order.route'].create({'mes_order_id': self.id})
            operation = self.env['sn.wsd.operation'].create({
                'name': 'Test Operation %s' % self.id, 'code': 'TEST-OP-%s' % self.id,
            })
            self.env['sn.wsd.mes.order.route.operation'].create({
                'mes_route_id': route.id,
                'operation_id': operation.id,
                'sequence': 10,
            })
            return True

        with patch.object(MesOrder, '_setup_route', _fake_setup_route):
            return cls.env['sn.wsd.mes.order'].create({
                'production_id': production.id,
                'production_line_id': cls.production_line.id,
                'date_plan': fields.Date.today(),
                'planned_qty': qty,
            })

    def _make_serial_defective(self, serial):
        self.env['sn.wsd.quality.issue'].create({
            'serial_identity_id': serial.id,
            'route_operation_id': self.route_operation.id,
            'defect_code_id': self.defect_code.id,
            'issue_source': 'manual',
        })

    def _create_order(self, **kw):
        vals = {
            'serial_identity_id': self.serial.id,
            'serial_no': self.serial.name,
            'defect_code_id': self.defect_code.id,
            'defect_line_ids': [(0, 0, {
                'defect_code_id': self.defect_code.id, 'qty': 1})],
        }
        vals.update(kw)
        return self.env['sn.wsd.repair.order'].create(vals)

    # ------------------------------------------------------------------
    # Failure cause dictionary
    # ------------------------------------------------------------------

    def test_cause_code_unique(self):
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['sn.wsd.repair.cause'].create(
                    {'name': 'Cause %s' % self.failure_cause.code, 'code': self.failure_cause.code})

    def test_cause_name_unique(self):
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['sn.wsd.repair.cause'].create(
                    {'name': self.failure_cause.name, 'code': 'C99-%s' % self.failure_cause.id})

    # ------------------------------------------------------------------
    # Order fields and rework entry
    # ------------------------------------------------------------------

    def test_entry_defaults_to_defect_operation(self):
        self._make_serial_defective(self.serial)
        
        order = self._create_order()
        order.action_report_repair()
        self.assertEqual(order.repair_entry_route_operation_id, self.route_operation)

    def test_entry_cross_mes_order_blocked(self):
        self._make_serial_defective(self.serial)
        other_production = self.env['mrp.production'].create({
            'product_id': self.production.product_id.id,
            'product_qty': 5,
        })
        other_order = self._create_mes_order(other_production, 5)
        other_operation = other_order.x_route_operation_ids[0] if other_order.x_route_operation_ids else False
        if not other_operation:
            self.skipTest('no route operations materialized')
        order = self._create_order()
        with self.assertRaises(ValidationError):
            order.repair_entry_route_operation_id = other_operation

    def test_production_is_trace_only(self):
        self._make_serial_defective(self.serial)
        order = self._create_order()
        order.action_report_repair()
        self.assertEqual(order.production_id, self.production)
        # The entry domain is the MES order, production route no longer drives it
        self.assertEqual(order.mes_order_id, self.mes_order)

    # ------------------------------------------------------------------
    # Full lifecycle
    # ------------------------------------------------------------------

    def test_full_flow_repair_ok(self):
        self._make_serial_defective(self.serial)
        
        order = self._create_order(
            defect_location='U12',
            failure_cause_id=self.failure_cause.id,
        )
        order.action_report_repair()
        self.assertEqual(order.state, 'reported')
        self.assertTrue(order.quality_issue_id)
        order.action_start_repair()
        self.assertEqual(order.state, 'repairing')
        self.assertEqual(
            self.route_operation, order.repair_entry_route_operation_id)
        order.action_repair_ok()
        self.assertEqual(order.state, 'done')
        self.assertEqual(order.result, 'ok')
        self.assertEqual(self.serial.x_quality_hold_state, 'released')
        self.assertEqual(order.quality_issue_id.state, 'closed')

    def test_full_flow_repair_scrap(self):
        self._make_serial_defective(self.serial)
        
        order = self._create_order()
        order.action_report_repair()
        with self.assertRaises(UserError):
            order.action_repair_scrap()  # reason required
        order.scrap_reason_id = self.scrap_reason.id
        order.action_repair_scrap()
        self.assertEqual(order.state, 'scrapped')
        self.assertTrue(order.scrap_record_id)
        self.assertEqual(order.scrap_record_id.mes_order_id, self.mes_order)

    def test_report_requires_defect_lines(self):
        self._make_serial_defective(self.serial)
        
        order = self._create_order(defect_line_ids=[(5, 0, 0)])
        with self.assertRaises(UserError):
            order.action_report_repair()

    def test_report_derives_main_defect(self):
        self._make_serial_defective(self.serial)
        
        order = self._create_order(defect_code_id=False)
        order.action_report_repair()
        self.assertEqual(order.defect_code_id, self.defect_code)

    def test_sn_onchange_prefills_lines_from_issues(self):
        from odoo.tests import Form
        self._make_serial_defective(self.serial)
        self.env['sn.wsd.quality.issue'].create({
            'serial_identity_id': self.serial.id,
            'defect_code_id': self.defect_code.id,
            'issue_source': 'repair',
            'state': 'open',
        })
        with Form(self.env['sn.wsd.repair.order']) as f:
            f.serial_identity_id = self.serial
            self.assertEqual(len(f.defect_line_ids), 1)
        order = f.save()
        self.assertEqual(order.defect_line_ids.defect_code_id, self.defect_code)

    def test_good_serial_not_reportable(self):
        order = self._create_order()
        with self.assertRaises(UserError):
            order.action_report_repair()

    # ------------------------------------------------------------------
    # PDA service
    # ------------------------------------------------------------------

    def test_service_unknown_sn(self):
        with self.assertRaises(UserError):
            self.env['sn.wsd.repair.service'].report('NOPE-404', 'D01')

    def test_service_good_sn_blocked(self):
        with self.assertRaises(UserError):
            self.env['sn.wsd.repair.service'].report('RP-SN-001', 'D01')

    def test_service_unknown_defect_code(self):
        self._make_serial_defective(self.serial)
        with self.assertRaises(UserError):
            self.env['sn.wsd.repair.service'].report('RP-SN-001', 'NO-SUCH-CODE')

    def test_service_full_flow(self):
        service = self.env['sn.wsd.repair.service']
        self._make_serial_defective(self.serial)
        
        info = service.resolve('RP-SN-001')
        self.assertEqual(info['sn'], 'RP-SN-001')
        message = service.report(
            'RP-SN-001', 'D01', location='U12', cause='C01', note='cold joint')
        self.assertIn('RP-SN-001', message)
        serial, order = service._get_open_order('RP-SN-001')
        self.assertEqual(order.state, 'reported')
        self.assertEqual(order.defect_location, 'U12')
        self.assertEqual(order.failure_cause_id, self.failure_cause)
        service.start('RP-SN-001')
        self.assertEqual(order.state, 'repairing')
        service.ok('RP-SN-001', method='reflow', cause='C01')
        self.assertEqual(order.state, 'done')
        self.assertEqual(order.result, 'ok')
        with self.assertRaises(UserError):
            # finished SN has no open order anymore
            service.ok('RP-SN-001')

    def test_service_scrap_flow(self):
        service = self.env['sn.wsd.repair.service']
        self._make_serial_defective(self.serial)
        
        service.report('RP-SN-001', 'D01')
        service.start('RP-SN-001')
        message = service.scrap('RP-SN-001', 'SCR01')
        self.assertIn('RP-SN-001', message)
        order = self.env['sn.wsd.repair.order'].search(
            [('serial_identity_id', '=', self.serial.id)], order='id desc', limit=1)
        self.assertEqual(order.state, 'scrapped')
        self.assertTrue(order.scrap_record_id)

class TestRepairDefectLines(TestRepair):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # quantity repair runs on report-mode MES orders
        cls.mes_order.x_manage_mode = 'report'

    def test_main_defect_autofill(self):
        from odoo.tests import Form
        with Form(self.env['sn.wsd.repair.order']) as f:
            f.route_operation_id = self.route_operation
            with f.defect_line_ids.new() as line:
                line.defect_code_id = self.defect_code
                line.qty = 3
            with f.defect_line_ids.new() as line:
                line.defect_code_id = self.defect_code
                line.qty = 1
            self.assertEqual(f.defect_qty, 4.0)
        order = f.save()
        self.assertEqual(len(order.defect_line_ids), 2)
        order.action_report_repair()
        self.assertEqual(order.defect_code_id, self.defect_code)

    def test_qty_mode_line_total_exceeds_blocked(self):
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.repair.order'].create({
                'route_operation_id': self.route_operation.id,
                'defect_code_id': self.defect_code.id,
                'defect_qty': 3.0,
                'defect_line_ids': [(0, 0, {
                    'defect_code_id': self.defect_code.id, 'qty': 5})],
            })

    def test_sn_mode_line_qty_must_be_one(self):
        self._make_serial_defective(self.serial)
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.repair.order'].create({
                'serial_identity_id': self.serial.id,
                'serial_no': self.serial.name,
                'defect_line_ids': [(0, 0, {
                    'defect_code_id': self.defect_code.id, 'qty': 2})],
            })

    def test_service_report_with_lines(self):
        # service.report is the SN flow: run it on a station-mode order
        self.mes_order.x_manage_mode = 'station'
        self._make_serial_defective(self.serial)
        
        service = self.env['sn.wsd.repair.service']
        message = service.report('RP-SN-001', 'D01', lines=[
            {'defect_code': 'D01', 'qty': 1, 'location': 'U12'},
        ])
        self.assertIn('RP-SN-001', message)
        order = self.env['sn.wsd.repair.order'].search(
            [('serial_identity_id', '=', self.serial.id)], order='id desc', limit=1)
        self.assertEqual(len(order.defect_line_ids), 1)
        self.assertEqual(order.defect_line_ids[0].defect_location, 'U12')
