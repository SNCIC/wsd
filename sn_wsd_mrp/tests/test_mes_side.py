from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMesSide(TransactionCase):
    """SMT board-side scheduling (电子线 MES - SMT 面别与工艺路线设计).

    Covers: the MO-driven process route check (车间 + 图号 + 面别), the
    side- and workshop-aware drawing/route binding, the default-side
    semantics (side-less route = single) and the per-side independence of
    the scheduling wizard (a full Top side never blocks the Bottom side).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.ws1 = cls.env['sn.mrp.workshop'].create({'name': 'WS-SIDE-1', 'code': 'WSS1'})
        cls.ws2 = cls.env['sn.mrp.workshop'].create({'name': 'WS-SIDE-2', 'code': 'WSS2'})
        cls.line1 = cls.env['sn.mrp.production.line'].create({
            'name': 'LS1', 'code': 'LS1', 'workshop_id': cls.ws1.id,
        })
        cls.line2 = cls.env['sn.mrp.production.line'].create({
            'name': 'LS2', 'code': 'LS2', 'workshop_id': cls.ws2.id,
        })
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({'name': 'OP-S-IN', 'code': 'SIN1', 'x_station_type': 'assembly'})
        cls.op_out = Operation.create({'name': 'OP-S-OUT', 'code': 'SOUT1', 'x_station_type': 'final_test'})

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_route(self, drawing, side=False, workshop=None, code='RT-SIDE'):
        """A confirmed live route bound to the drawing (with a flow graph, so
        MES orders can materialize their private route from it)."""
        workshop = workshop or self.ws1
        route = self.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True,
        ).create({
            'name': 'RT-%s' % code, 'code': code,
            'x_workshop_id': workshop.id,
            'x_production_side': side,
            'x_drawing_ids': [(0, 0, {'x_drawing_no': drawing})],
        })
        route.write({
            'state': 'confirmed',
            'route_operation_ids': [
                (0, 0, {'operation_id': self.op_in.id, 'sequence': 10}),
                (0, 0, {'operation_id': self.op_out.id, 'sequence': 20}),
            ],
            'x_daily_input_operation_id': self.op_in.id,
            'x_daily_output_operation_id': self.op_out.id,
            'x_workorder_input_operation_id': self.op_in.id,
        })
        return route

    def _make_product(self, drawing, board_side=False, name='P-SIDE'):
        return self.env['product.product'].create({
            'name': name, 'uom_id': self.uom_unit.id,
            'default_code': drawing, 'x_board_side': board_side,
        })

    def _make_legacy_product(self, drawing, name='P-LEGACY'):
        """Simulate a pre-default row: drawing number set (the internal
        reference carries it now), board side type NULL (both the field
        default and the ORM constraint forbid creating those now). Both the
        template columns and the variant's stored related columns are set,
        bypassing the ORM like a real legacy row."""
        product = self.env['product.product'].create({
            'name': name, 'uom_id': self.uom_unit.id,
        })
        tmpl_id = product.product_tmpl_id.id
        # flush pending towrite first, or the deferred related-store write
        # would overwrite the SQL update afterwards
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE product_template SET default_code = %s, x_board_side = NULL"
            " WHERE id = %s", (drawing, tmpl_id))
        self.env.cr.execute(
            "UPDATE product_product SET default_code = %s, x_board_side = NULL"
            " WHERE product_tmpl_id = %s", (drawing, tmpl_id))
        product.invalidate_recordset(['default_code', 'x_board_side'])
        return product

    def _make_mo(self, product, qty=1000, workshop=None):
        return self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': qty,
            'company_id': self.company.id,
            'x_workshop_id': (workshop or self.ws1).id,
        })

    def _make_wizard(self, mo, side='single', qty=100, line=None):
        return self.env['sn.wsd.mes.schedule.wizard'].create({
            'production_id': mo.id,
            'production_line_id': (line or self.line1).id,
            'date_plan': fields.Date.today(),
            'qty': qty,
            'x_side': side,
        })

    # ------------------------------------------------------------------
    # product master data: board side type is the source of truth
    # ------------------------------------------------------------------
    def test_01_drawing_product_requires_board_side(self):
        with self.assertRaises(ValidationError):
            self._make_product('DWG-BAD', False, name='P-BAD')

    def test_02_component_without_drawing_out_of_scope(self):
        product = self.env['product.product'].create({
            'name': 'P-RAW', 'uom_id': self.uom_unit.id,
        })
        mo = self._make_mo(product)
        self.assertFalse(mo.x_mes_route_missing)
        self.assertFalse(mo.x_mes_route_missing_sides)

    def test_03_undeclared_board_side_blocked(self):
        """Drawing products without a board side type (legacy rows) are
        incomplete master data: flagged in the check view and blocked at
        scheduling."""
        self._make_route('DWG-L0', 'single', code='RT-L0')
        product = self._make_legacy_product('DWG-L0')
        mo = self._make_mo(product)
        self.assertTrue(mo.x_mes_route_missing)
        self.assertEqual(mo.x_mes_route_missing_sides, 'Board Side Type')
        wizard = self._make_wizard(mo, side='single', qty=100)
        self.assertFalse(wizard.x_route_ok)
        with self.assertRaises(ValidationError) as err:
            wizard.action_schedule()
        self.assertIn('board side type declared', str(err.exception))
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.mes.order'].create({
                'production_id': mo.id,
                'production_line_id': self.line1.id,
                'date_plan': fields.Date.today(),
                'planned_qty': 10,
                'x_side': 'single',
            })

    # ------------------------------------------------------------------
    # process route check view (工艺路线检查视图): 车间 + 图号 + 面别
    # ------------------------------------------------------------------
    def test_10_mo_check_missing_bottom(self):
        self._make_route('DWG-C10', 'top', code='RT-C10T')
        product = self._make_product('DWG-C10', 'double')
        mo = self._make_mo(product)
        self.assertTrue(mo.x_mes_route_top_ok)
        self.assertFalse(mo.x_mes_route_bottom_ok)
        self.assertTrue(mo.x_mes_route_missing)
        self.assertIn('Bottom (B)', mo.x_mes_route_missing_sides)
        # searchable through the default filter of the check view
        found = self.env['mrp.production'].search([
            ('id', '=', mo.id), ('x_mes_route_missing', '=', True)])
        self.assertEqual(found, mo)
        # adding the bottom route clears the flag
        self._make_route('DWG-C10', 'bottom', code='RT-C10B')
        mo.invalidate_recordset()
        self.assertFalse(mo.x_mes_route_missing)
        self.assertFalse(mo.x_mes_route_missing_sides)

    def test_11_mo_check_single_requires_explicit_side(self):
        """未设面别的路线不匹配任何面：single 也必须显式声明。"""
        self._make_route('DWG-C11', False, code='RT-C11')
        product = self._make_product('DWG-C11', 'single')
        mo = self._make_mo(product)
        self.assertFalse(mo.x_mes_route_single_ok)
        self.assertTrue(mo.x_mes_route_missing)
        self.assertIn('Single', mo.x_mes_route_missing_sides)
        # 补上显式单面路线后恢复
        self._make_route('DWG-C11', 'single', code='RT-C11S')
        mo.invalidate_recordset()
        self.assertTrue(mo.x_mes_route_single_ok)
        self.assertFalse(mo.x_mes_route_missing)

    def test_12_mo_check_double_ignores_sideless(self):
        self._make_route('DWG-C12', False, code='RT-C12')
        product = self._make_product('DWG-C12', 'double')
        mo = self._make_mo(product)
        self.assertTrue(mo.x_mes_route_missing)
        self.assertIn('Top (T)', mo.x_mes_route_missing_sides)
        self.assertIn('Bottom (B)', mo.x_mes_route_missing_sides)

    def test_13_mo_check_workshop_must_match(self):
        """车间 is part of the matching key: a route bound in another
        workshop does not satisfy this MO."""
        self._make_route('DWG-C13', 'top', workshop=self.ws2, code='RT-C13T')
        product = self._make_product('DWG-C13', 'double')
        mo = self._make_mo(product, workshop=self.ws1)
        self.assertTrue(mo.x_mes_route_missing)
        self.assertIn('Top (T)', mo.x_mes_route_missing_sides)
        # the same drawing gets its own route in ws1: both workshops coexist
        self._make_route('DWG-C13', 'top', workshop=self.ws1, code='RT-C13T1')
        self._make_route('DWG-C13', 'bottom', workshop=self.ws1, code='RT-C13B1')
        mo.invalidate_recordset()
        self.assertFalse(mo.x_mes_route_missing)

    def test_14_mo_check_button_action_prefills(self):
        self._make_route('DWG-C14', 'top', code='RT-C14T')
        product = self._make_product('DWG-C14', 'double')
        mo = self._make_mo(product, workshop=self.ws2)
        action = mo.action_mes_add_bottom_route()
        self.assertEqual(action['res_model'], 'sn.wsd.process.route')
        self.assertEqual(action['context']['default_x_production_side'], 'bottom')
        self.assertEqual(action['context']['default_x_workshop_id'], self.ws2.id)
        self.assertEqual(
            action['context']['default_x_drawing_ids'],
            [(0, 0, {'x_drawing_no': 'DWG-C14'})])

    # ------------------------------------------------------------------
    # side- and workshop-aware binding + resolver
    # ------------------------------------------------------------------
    def test_20_binding_unique_per_workshop_side(self):
        self._make_route('DWG-U1', 'top', workshop=self.ws1, code='RT-U1T')
        # same drawing, other side or other workshop: allowed
        self._make_route('DWG-U1', 'bottom', workshop=self.ws1, code='RT-U1B')
        self._make_route('DWG-U1', 'top', workshop=self.ws2, code='RT-U1T2')
        # same drawing + side + workshop: rejected
        route = self.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True,
        ).create({
            'name': 'RT-U1T3', 'code': 'RT-U1T3',
            'x_workshop_id': self.ws1.id,
            'x_production_side': 'top',
        })
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['sn.wsd.process.route.drawing'].create({
                    'route_id': route.id, 'x_drawing_no': 'DWG-U1',
                })
                self.env.flush_all()

    def test_21_resolver_filters_side_and_workshop(self):
        route_top = self._make_route('DWG-R1', 'top', workshop=self.ws1, code='RT-R1T')
        route_bottom = self._make_route('DWG-R1', 'bottom', workshop=self.ws1, code='RT-R1B')
        self._make_route('DWG-R1', 'top', workshop=self.ws2, code='RT-R1T2')
        Route = self.env['sn.wsd.process.route']
        self.assertEqual(
            Route._find_current_route_by_drawing_no(
                'DWG-R1', self.company.id, side='top', workshop_id=self.ws1.id),
            route_top)
        self.assertEqual(
            Route._find_current_route_by_drawing_no(
                'DWG-R1', self.company.id, side='bottom', workshop_id=self.ws1.id),
            route_bottom)
        # wrong workshop: no match
        self.assertFalse(
            Route._find_current_route_by_drawing_no(
                'DWG-R1', self.company.id, side='bottom', workshop_id=self.ws2.id))
        # side-less route matches no side
        self._make_route('DWG-R2', False, code='RT-R2')
        self.assertFalse(
            Route._find_current_route_by_drawing_no(
                'DWG-R2', self.company.id, side='single', workshop_id=self.ws1.id))
        self.assertFalse(
            Route._find_current_route_by_drawing_no(
                'DWG-R2', self.company.id, side='top', workshop_id=self.ws1.id))

    # ------------------------------------------------------------------
    # per-side scheduling through the wizard (面别各自独立)
    # ------------------------------------------------------------------
    def test_30_sides_schedule_independently(self):
        self._make_route('DWG-M1', 'top', code='RT-M1T')
        self._make_route('DWG-M1', 'bottom', code='RT-M1B')
        product = self._make_product('DWG-M1', 'double')
        mo = self._make_mo(product, qty=1000)
        # each side may cover the FULL MO quantity
        self._make_wizard(mo, side='top', qty=1000).action_schedule()
        with self.assertRaises(ValidationError):
            self._make_wizard(mo, side='top', qty=1).action_schedule()
        self._make_wizard(mo, side='bottom', qty=1000).action_schedule()
        with self.assertRaises(ValidationError):
            self._make_wizard(mo, side='bottom', qty=1).action_schedule()
        orders = mo.x_mes_order_ids
        self.assertEqual(len(orders), 2)
        self.assertEqual(sorted(orders.mapped('x_side')), ['bottom', 'top'])

    def test_31_wizard_blocked_when_side_route_missing(self):
        self._make_route('DWG-M2', 'top', code='RT-M2T')
        product = self._make_product('DWG-M2', 'double')
        mo = self._make_mo(product, qty=100)
        wizard = self._make_wizard(mo, side='bottom', qty=10)
        self.assertFalse(wizard.x_route_ok)
        with self.assertRaises(ValidationError) as err:
            wizard.action_schedule()
        self.assertIn('not maintained', str(err.exception))
        # the top side keeps scheduling (生产不空转)
        self._make_wizard(mo, side='top', qty=100).action_schedule()
        self.assertEqual(mo.x_mes_order_ids.x_side, 'top')

    def test_32_wizard_route_gate_uses_line_workshop(self):
        """The route gate matches the workshop of the chosen production
        line, not just the MO's own workshop."""
        self._make_route('DWG-M3', 'top', workshop=self.ws1, code='RT-M3T')
        self._make_route('DWG-M3', 'top', workshop=self.ws2, code='RT-M3T2')
        product = self._make_product('DWG-M3', 'double')
        mo = self._make_mo(product, qty=100, workshop=self.ws2)
        # line 2 has its own top route -> schedules fine
        self._make_wizard(mo, side='top', qty=10, line=self.line2).action_schedule()
        # line 1 has no BOTTOM route -> blocked although the MO workshop has one
        self._make_route('DWG-M3', 'bottom', workshop=self.ws2, code='RT-M3B')
        wizard = self._make_wizard(mo, side='bottom', qty=10, line=self.line1)
        self.assertFalse(wizard.x_route_ok)
        with self.assertRaises(ValidationError):
            wizard.action_schedule()

    def test_33_maintain_route_action_prefills(self):
        self._make_route('DWG-M4', 'top', code='RT-M4T')
        product = self._make_product('DWG-M4', 'double')
        mo = self._make_mo(product, qty=100)
        wizard = self._make_wizard(mo, side='bottom', qty=10)
        action = wizard.action_maintain_route()
        self.assertEqual(action['res_model'], 'sn.wsd.process.route')
        self.assertEqual(action['context']['default_x_production_side'], 'bottom')
        self.assertEqual(action['context']['default_x_workshop_id'], self.ws1.id)
        self.assertEqual(
            action['context']['default_x_drawing_ids'],
            [(0, 0, {'x_drawing_no': 'DWG-M4'})])

    def test_34_side_default_from_board_type(self):
        self._make_route('DWG-M5', 'top', code='RT-M5T')
        self._make_route('DWG-M5', 'bottom', code='RT-M5B')
        product = self._make_product('DWG-M5', 'double')
        mo = self._make_mo(product, qty=100)
        wizard = self.env['sn.wsd.mes.schedule.wizard'].new({
            'production_id': mo.id,
        })
        wizard._onchange_production_id_side()
        self.assertEqual(wizard.x_side, 'top')
        single_product = self._make_product('DWG-M6', 'single', name='P-SINGLE')
        self._make_route('DWG-M6', 'single', code='RT-M6')
        mo2 = self._make_mo(single_product, qty=100)
        wizard2 = self.env['sn.wsd.mes.schedule.wizard'].new({
            'production_id': mo2.id,
        })
        wizard2._onchange_production_id_side()
        self.assertEqual(wizard2.x_side, 'single')

    def test_35_order_side_must_match_board(self):
        # a double-sided drawing may legitimately carry a single route too
        self._make_route('DWG-C1', 'top', code='RT-C1T')
        self._make_route('DWG-C1', 'bottom', code='RT-C1B')
        self._make_route('DWG-C1', 'single', code='RT-C1S')
        double_product = self._make_product('DWG-C1', 'double')
        mo = self._make_mo(double_product, qty=100)
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.mes.order'].create({
                'production_id': mo.id,
                'production_line_id': self.line1.id,
                'date_plan': fields.Date.today(),
                'planned_qty': 10,
                'x_side': 'single',
            })
        single_product = self._make_product('DWG-C2', 'single', name='P-C2')
        self._make_route('DWG-C2', 'single', code='RT-C2S')
        self._make_route('DWG-C2', 'top', code='RT-C2T')
        mo2 = self._make_mo(single_product, qty=100)
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.mes.order'].create({
                'production_id': mo2.id,
                'production_line_id': self.line1.id,
                'date_plan': fields.Date.today(),
                'planned_qty': 10,
                'x_side': 'top',
            })

    def test_36_order_snapshots_side_route(self):
        route_bottom = self._make_route('DWG-P1', 'bottom', code='RT-P1B')
        self._make_route('DWG-P1', 'top', code='RT-P1T')
        product = self._make_product('DWG-P1', 'double')
        mo = self._make_mo(product, qty=100)
        self._make_wizard(mo, side='bottom', qty=100).action_schedule()
        order = mo.x_mes_order_ids
        self.assertEqual(order.x_side, 'bottom')
        self.assertEqual(order.x_mes_route_id.route_id, route_bottom)

    def test_37_line_workshop_must_match_mo(self):
        """排产线必须属于 MO 的车间：即使产线车间有自己的路线，也不允许
        跨车间排产（与工艺路线检查视图按 MO 车间判定保持一致）。"""
        self._make_route('DWG-W1', 'top', workshop=self.ws1, code='RT-W1T')
        self._make_route('DWG-W1', 'bottom', workshop=self.ws1, code='RT-W1B')
        product = self._make_product('DWG-W1', 'double')
        mo = self._make_mo(product, qty=100, workshop=self.ws2)
        wizard = self._make_wizard(mo, side='top', qty=10, line=self.line1)
        self.assertTrue(wizard.x_route_ok, 'ws1 does have both routes')
        with self.assertRaises(ValidationError) as err:
            wizard.action_schedule()
        self.assertIn('belongs to workshop', str(err.exception))
