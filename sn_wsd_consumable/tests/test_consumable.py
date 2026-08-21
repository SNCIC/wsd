import psycopg2
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestConsumable(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env['sn.consumable.template'].create({
            'code': 'AUX-TST-001',
            'name': 'Test Solder Paste',
            'consumable_type': 'solder_paste',
            'thaw_duration_min': 0,
            'thaw_duration_max': 120,
            'thaw_count_limit': 2,
            'stir_control': True,
            'stir_duration_min': 0,
            'stir_duration_max': 5,
            'shelf_life_days': 180,
            'expiry_remind_days': 7,
        })
        cls.info = cls.env['sn.consumable.info'].create({
            'sn': 'AUX-SN-001',
            'template_id': cls.template.id,
            'production_date': fields.Date.today(),
        })
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'AUX TEST WS'})
        cls.production_line = cls.env['sn.mrp.production.line'].create({
            'name': 'AUX TEST LINE',
            'workshop_id': cls.workshop.id,
            'company_id': cls.env.company.id,
        })
        cls.production = cls.env['mrp.production'].create({
            'product_id': cls.env['product.product'].create({'name': 'AUX Product'}).id,
            'product_qty': 10,
        })
        cls.mes_order = cls._create_mes_order(cls.production, 10)

    @classmethod
    def _create_mes_order(cls, production, qty):
        # Route materialization requires a released process route bound to the
        # drawing number; consumable logic never touches routes, skip it here.
        MesOrder = cls.env['sn.wsd.mes.order']
        with patch.object(type(MesOrder), '_setup_route', lambda self: True):
            return MesOrder.create({
                'production_id': production.id,
                'production_line_id': cls.production_line.id,
                'date_plan': fields.Date.today(),
                'planned_qty': qty,
            })

    def _thaw_ok(self, info):
        info.action_thaw_start()
        info.action_thaw_end()

    def _stir_ok(self, info):
        info.action_stir_start()
        info.action_stir_end()

    # ------------------------------------------------------------------
    # Template
    # ------------------------------------------------------------------

    def test_template_code_unique(self):
        with self.assertRaises(psycopg2.IntegrityError):
            with self.env.cr.savepoint():
                self.env['sn.consumable.template'].create({
                    'code': 'AUX-TST-001',
                    'name': 'Dup',
                    'consumable_type': 'flux',
                    'shelf_life_days': 30,
                    'expiry_remind_days': 3,
                })

    def test_type_prefill_defaults(self):
        with Form(self.env['sn.consumable.template']) as template_form:
            template_form.code = 'AUX-TST-002'
            template_form.name = 'Prefill'
            template_form.consumable_type = 'red_glue'
            template_form.shelf_life_days = 90
            template_form.expiry_remind_days = 5
            self.assertEqual(template_form.thaw_duration_min, 0)
            self.assertEqual(template_form.thaw_duration_max, 133)
        self.assertEqual(
            self.env['sn.consumable.template'].search([('code', '=', 'AUX-TST-002')]).thaw_duration_max, 133)

    def test_thaw_duration_constraint(self):
        with self.assertRaises(ValidationError):
            self.template.write({'thaw_duration_min': 130})

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def test_info_sn_unique(self):
        with self.assertRaises(psycopg2.IntegrityError):
            with self.env.cr.savepoint():
                self.env['sn.consumable.info'].create({
                    'sn': 'AUX-SN-001',
                    'template_id': self.template.id,
                })

    def test_expiry_compute(self):
        self.assertEqual(
            self.info.expiry_date, fields.Date.add(fields.Date.today(), days=180))
        self.assertEqual(self.info.expiry_state, 'ok')
        self.info.production_date = fields.Date.add(fields.Date.today(), days=-176)
        self.assertEqual(self.info.expiry_state, 'remind')
        self.info.production_date = fields.Date.add(fields.Date.today(), days=-200)
        self.assertEqual(self.info.expiry_state, 'expired')

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def test_thaw_flow(self):
        self.info.action_thaw_start()
        self.assertEqual(self.info.aux_state, 'thawing')
        self.assertEqual(self.info.thaw_count, 1)
        self.info.action_thaw_end()
        self.assertEqual(self.info.aux_state, 'ready')
        records = self.info.record_ids.filtered(lambda r: r.action == 'thaw_end')
        self.assertEqual(len(records), 1)
        self.assertEqual(records.thaw_count, 1)

    def test_thaw_requires_normal(self):
        self.info.action_thaw_start()
        with self.assertRaises(UserError):
            self.info.action_thaw_start()

    def test_thaw_short_blocked(self):
        self.template.write({'thaw_duration_min': 60})
        self.info.action_thaw_start()
        with self.assertRaises(UserError):
            self.info.action_thaw_end()
        self.assertEqual(self.info.aux_state, 'thawing')

    def test_thaw_over_limit_blocked(self):
        self.info.action_thaw_start()
        self.info.write({'thaw_start': fields.Datetime.now() - timedelta(hours=3)})
        with self.assertRaises(UserError):
            self.info.action_thaw_end()
        self.assertEqual(self.info.aux_state, 'thawing')

    def test_thaw_count_limit(self):
        # limit is 2: thaw/stir/load/unload twice, the third thaw must be blocked
        for _ in range(2):
            self._thaw_ok(self.info)
            self._stir_ok(self.info)
            self.info.action_load(self.mes_order)
            self.info.action_unload()
        with self.assertRaises(UserError):
            self.info.action_thaw_start()

    def test_expired_blocks_thaw(self):
        self.info.production_date = fields.Date.add(fields.Date.today(), days=-400)
        with self.assertRaises(UserError):
            self.info.action_thaw_start()

    def test_stir_required_before_load(self):
        self._thaw_ok(self.info)
        with self.assertRaises(UserError):
            self.info.action_load(self.mes_order)
        self._stir_ok(self.info)
        self.info.action_load(self.mes_order)
        self.assertEqual(self.info.aux_state, 'in_use')

    def test_stir_short_blocked(self):
        self.template.write({'stir_duration_min': 3})
        self._thaw_ok(self.info)
        self.info.action_stir_start()
        with self.assertRaises(UserError):
            self.info.action_stir_end()

    def test_no_stir_control_load_direct(self):
        self.template.write({'stir_control': False})
        self._thaw_ok(self.info)
        self.info.action_load(self.mes_order)
        self.assertEqual(self.info.aux_state, 'in_use')

    def test_load_unload_record_mes_order(self):
        self._thaw_ok(self.info)
        self._stir_ok(self.info)
        self.info.action_load(self.mes_order)
        self.info.action_unload()
        self.assertEqual(self.info.aux_state, 'normal')
        load = self.info.record_ids.filtered(lambda r: r.action == 'load')
        unload = self.info.record_ids.filtered(lambda r: r.action == 'unload')
        self.assertEqual(load.mes_order_id, self.mes_order)
        self.assertEqual(unload.mes_order_id, self.mes_order)

    def test_terminal_states(self):
        self._thaw_ok(self.info)
        self._stir_ok(self.info)
        self.info.action_load(self.mes_order)
        self.info.action_exhaust()
        self.assertEqual(self.info.aux_state, 'exhausted')
        with self.assertRaises(UserError):
            self.info.action_thaw_start()
        with self.assertRaises(UserError):
            self.info.action_scrap(reason='test')

    def test_scrap_with_reason(self):
        self.info.action_scrap(reason='damaged')
        self.assertEqual(self.info.aux_state, 'scrapped')
        record = self.info.record_ids.filtered(lambda r: r.action == 'scrap')
        self.assertEqual(record.scrap_reason, 'damaged')

    def test_disable_enable(self):
        self.info.action_disable()
        self.assertEqual(self.info.aux_state, 'disabled')
        with self.assertRaises(UserError):
            self.info.action_thaw_start()
        self.info.action_enable()
        self.assertEqual(self.info.aux_state, 'normal')

    # ------------------------------------------------------------------
    # PDA service
    # ------------------------------------------------------------------

    def test_service_resolve_unknown(self):
        with self.assertRaises(UserError):
            self.env['sn.consumable.service'].resolve('NOPE-123')

    def test_service_full_flow(self):
        service = self.env['sn.consumable.service']
        resolved = service.resolve('AUX-SN-001')
        self.assertEqual(resolved['template_code'], 'AUX-TST-001')
        service.thaw_start('AUX-SN-001')
        service.thaw_end('AUX-SN-001')
        service.stir_start('AUX-SN-001')
        service.stir_end('AUX-SN-001')
        message = service.load('AUX-SN-001', self.mes_order.name)
        self.assertIn('AUX-SN-001', message)
        self.assertEqual(self.info.aux_state, 'in_use')
        service.unload('AUX-SN-001')
        service.exhaust('AUX-SN-001')
        self.assertEqual(self.info.aux_state, 'exhausted')

    def test_service_load_unknown_mes_order(self):
        self._thaw_ok(self.info)
        self._stir_ok(self.info)
        with self.assertRaises(UserError):
            self.env['sn.consumable.service'].load('AUX-SN-001', 'NO/SUCH/ORDER')
