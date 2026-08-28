from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMesOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'WS-T', 'code': 'WST'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LA', 'code': 'LA', 'workshop_id': cls.workshop.id,
        })
        # BOM 车间独立于产线车间：多步仓库（pbm/pbm_sam）下 MO 源库位会跟随
        # BOM 车间的线边库，若与产线车间共用会让 MES 领料"源=目的地"。这里按
        # 仓库步数把 BOM 车间库位配置在预生产/后生产区域下，满足
        # _check_workshop_manufacturing_locations 的确认校验。
        cls.bom_workshop = cls.env['sn.mrp.workshop'].create({'name': 'WS-BOM', 'code': 'WSB'})
        cls.wh = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        if cls.wh and cls.wh.manufacture_steps != 'mrp_one_step' and cls.wh.pbm_loc_id:
            cls.bom_workshop.component_location_id = cls.env['stock.location'].create({
                'name': 'BOM-WS-COMP', 'usage': 'internal',
                'location_id': cls.wh.pbm_loc_id.id,
            }).id
        if cls.wh and cls.wh.manufacture_steps == 'pbm_sam' and cls.wh.sam_loc_id:
            cls.bom_workshop.finished_product_location_id = cls.env['stock.location'].create({
                'name': 'BOM-WS-FP', 'usage': 'internal',
                'location_id': cls.wh.sam_loc_id.id,
            }).id
        # sn_wsd_skip_flow_versioning: the module's own escape hatch, so route
        # creation in tests does not depend on the flow-versioning feature
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True,
        ).create({
            'name': 'RT', 'code': 'RT', 'x_workshop_id': cls.workshop.id,
        })
        # MES order creation resolves the common route through the product's
        # drawing number and materializes a private route from it: give the
        # test route two confirmed operations reachable via the legacy graph
        # (daily input and output must differ).
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({'name': 'OP-IN', 'code': 'IN1', 'x_station_type': 'assembly'})
        cls.op_out = Operation.create({'name': 'OP-OUT', 'code': 'OUT1', 'x_station_type': 'final_test'})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_out.id, 'sequence': 20}),
            ],
            'x_daily_input_operation_id': cls.op_in.id,
            'x_daily_output_operation_id': cls.op_out.id,
            'x_workorder_input_operation_id': cls.op_in.id,
        })
        # 图号 <-> 路线 只通过绑定表关联（解析不再回退路线上的老字段）
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-MES-TEST',
        })
        # station-mode flags on the legacy lines so the materialized private
        # routes carry start/end semantics for the pass-station tests; the
        # edge makes the output operation unreachable until the input one is
        # completed/reported-full (OR-join reachability)
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[1].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]

    def _make_mo(self, qty=10000):
        product = self.env['product.product'].create({
            'name': 'P-MES', 'uom_id': self.uom_unit.id, 'default_code': 'DWG-MES-TEST',
            'x_board_side': 'single',
        })
        return self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': qty, 'company_id': self.company.id,
        })

    def _make_order(self, mo, qty, line=None):
        return self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': (line or self.line).id,
            'date_plan': fields.Date.today(),
            'planned_qty': qty,
        })

    def _set_line_side(self):
        line_side = self.env['stock.location'].create({'name': 'LINE-SIDE', 'usage': 'internal'})
        self.workshop.component_location_id = line_side.id
        return line_side

    def _stock_component(self, mo, qty=100):
        """Put component stock in the MO source location so pickings validate."""
        self.env['stock.quant'].create({
            'product_id': mo.bom_id.bom_line_ids.product_id.id,
            'location_id': mo.location_src_id.id,
            'quantity': qty,
        })

    # --- F2: under-schedule and full schedule, with sequential names ---
    def test_01_under_and_full_schedule(self):
        mo = self._make_mo(10000)
        o1 = self._make_order(mo, 3000)
        self.assertEqual(o1.name, '%s-1' % mo.name)
        self.assertEqual(mo.x_mes_schedule_state, 'partial')
        self.assertAlmostEqual(mo.x_mes_scheduled_qty, 3000)
        self.assertAlmostEqual(mo.x_mes_unscheduled_qty, 7000)
        o2 = self._make_order(mo, 7000)
        self.assertEqual(o2.name, '%s-2' % mo.name)
        self.assertEqual(mo.x_mes_schedule_state, 'planned')
        self.assertAlmostEqual(mo.x_mes_scheduled_qty, 10000)

    # --- F2 R1: cannot over-schedule ---
    def test_02_over_schedule_blocked(self):
        mo = self._make_mo(10000)
        self._make_order(mo, 3000)
        self._make_order(mo, 7000)
        with self.assertRaises(ValidationError):
            self._make_order(mo, 500)

    # --- F2 R3 / F1: revoking a released order drops MO scheduled qty ---
    def test_03_cancel_revokes(self):
        mo = self._make_mo(10000)
        o1 = self._make_order(mo, 3000)
        self._make_order(mo, 7000)
        self.assertEqual(mo.x_mes_schedule_state, 'planned')
        o1.action_cancel()
        self.assertEqual(o1.state, 'cancelled')
        self.assertEqual(mo.x_mes_schedule_state, 'partial')
        self.assertAlmostEqual(mo.x_mes_scheduled_qty, 7000)

    # --- F3 R5: only Released orders can be cancelled ---
    def test_04_cancel_blocked_after_picked(self):
        mo = self._make_mo(1000)
        order = self._make_order(mo, 1000)
        order.state = 'picked'
        with self.assertRaises(ValidationError):
            order.action_cancel()

    # --- F2 R5: a released order's scheduling fields are frozen ---
    def test_05_released_immutable(self):
        mo = self._make_mo(1000)
        order = self._make_order(mo, 1000)
        with self.assertRaises(ValidationError):
            order.write({'planned_qty': 500})

    # --- F1 AC1: a fresh MO is unplanned ---
    def test_06_unplanned_state(self):
        mo = self._make_mo(1000)
        self.assertEqual(mo.x_mes_schedule_state, 'unplanned')
        self.assertAlmostEqual(mo.x_mes_scheduled_qty, 0)

    # ===== scheduling wizard (架构设计 3.1): the single entry point =====

    def test_10_schedule_wizard(self):
        mo = self._make_mo(10000)
        wizard = self.env['sn.wsd.mes.schedule.wizard'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'qty': 3000,
        })
        self.assertAlmostEqual(wizard.x_side_remaining_qty, 10000)
        wizard.action_schedule()
        order = mo.x_mes_order_ids
        self.assertEqual(len(order), 1)
        self.assertEqual(order.planned_qty, 3000)
        self.assertEqual(order.name, '%s-1' % mo.name)
        self.assertAlmostEqual(mo.x_mes_scheduled_qty, 3000)

    def test_11_schedule_wizard_over_blocked(self):
        mo = self._make_mo(1000)
        wizard = self.env['sn.wsd.mes.schedule.wizard'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'qty': 1000,
        })
        wizard.action_schedule()
        wizard2 = self.env['sn.wsd.mes.schedule.wizard'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'qty': 1,
        })
        with self.assertRaises(ValidationError):
            wizard2.action_schedule()
        self.assertEqual(len(mo.x_mes_order_ids), 1)

    # --- PRD R6: quantities are whole units ---
    def test_12_fractional_qty_blocked(self):
        mo = self._make_mo(1000)
        with self.assertRaises(ValidationError):
            self._make_order(mo, 100.5)

    # --- disabled production lines cannot be scheduled ---
    def test_13_inactive_line_blocked(self):
        mo = self._make_mo(1000)
        line = self.env['sn.mrp.production.line'].create({
            'name': 'LB', 'code': 'LB', 'workshop_id': self.workshop.id, 'active': False,
        })
        with self.assertRaises(ValidationError):
            self._make_order(mo, 100, line=line)

    # ===== F5: material picking =====

    def _make_bom_mo(self, qty=10):
        """MO backed by a BOM with one component line (2 per finished unit)."""
        product = self.env['product.product'].create({
            'name': 'P-MES-BOM', 'uom_id': self.uom_unit.id, 'default_code': 'DWG-MES-TEST',
            'x_board_side': 'single',
        })
        component = self.env['product.product'].create({
            'name': 'COMP', 'uom_id': self.uom_unit.id, 'is_storable': True,
        })
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_id': product.id,
            'product_uom_id': self.uom_unit.id,
            'product_qty': 1.0,
            'type': 'normal',
            'x_workshop_id': self.bom_workshop.id,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 2.0,
                'product_uom_id': self.uom_unit.id,
            })],
        })
        return self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': qty, 'bom_id': bom.id,
            'company_id': self.company.id,
        })

    # --- F5 AC1: picking generated with prorated qty, BOM-line UoM, on the order ---
    def test_07_generate_material_picking(self):
        line_side = self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        order = self._make_order(mo, 4)
        order.action_generate_picking()
        picking = order.picking_ids
        self.assertTrue(picking, 'a material picking must be created')
        self.assertEqual(picking.location_dest_id, line_side, 'destination must be the line-side location')
        self.assertEqual(picking.location_id, mo.picking_type_id.warehouse_id.lot_stock_id,
                         'source must be the warehouse main stock (Route X)')
        self.assertEqual(picking.x_mes_order_id, order)
        self.assertAlmostEqual(picking.x_mes_order_qty, 4.0)
        self.assertEqual(picking.picking_type_id.name, 'Material Issue',
                         'requisitions must use the dedicated Material Issue type')
        moves = picking.move_ids
        self.assertEqual(len(moves), 1)
        # qty = bom_line.product_qty(2) * planned(4) / bom.product_qty(1) = 8
        self.assertEqual(moves.product_uom_qty, 8.0)
        self.assertEqual(moves.product_uom, self.uom_unit, 'move UoM must be the BOM-line UoM')

    # --- F5 AC2: validating all pickings moves the MES order to picked ---
    def test_09_picking_done_transitions_to_picked(self):
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        self._stock_component(mo)
        order = self._make_order(mo, 4)
        order.action_generate_picking()
        picking = order.picking_ids
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(order.state, 'picked')
        self.assertAlmostEqual(order.picked_qty, 4.0)
        with self.assertRaises(ValidationError):
            order.action_cancel()

    # --- 架构设计 3.2: material already issued forbids cancellation ---
    def test_14_cancel_blocked_when_material_issued(self):
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        self._stock_component(mo)
        order = self._make_order(mo, 4)
        order.action_generate_picking(qty_this=2)
        picking = order.picking_ids
        picking.move_ids.picked = True
        picking.button_validate()
        # only half the units are picked -> the order is still released
        self.assertEqual(picking.state, 'done')
        self.assertEqual(order.state, 'released')
        self.assertAlmostEqual(order.picked_qty, 2.0)
        with self.assertRaises(ValidationError):
            order.action_cancel()

    # --- 架构设计 3.2: not-yet-issued pickings are cancelled with the order ---
    def test_15_cancel_cancels_open_pickings(self):
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        order = self._make_order(mo, 4)
        order.action_generate_picking()
        self.assertIn(order.picking_ids.state, ('confirmed', 'waiting', 'assigned'))
        order.action_cancel()
        self.assertEqual(order.state, 'cancelled')
        self.assertEqual(order.picking_ids.state, 'cancel')

    # --- 架构设计 3.3: batches accumulate in finished units ---
    def test_16_partial_pick_batches(self):
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        self._stock_component(mo)
        order = self._make_order(mo, 4)
        # first batch: 2 units -> 2 * 2 components
        order.action_generate_picking(qty_this=2)
        p1 = order.picking_ids
        self.assertAlmostEqual(p1.x_mes_order_qty, 2.0)
        self.assertAlmostEqual(p1.move_ids.product_uom_qty, 4.0)
        p1.move_ids.picked = True
        p1.button_validate()
        self.assertEqual(order.state, 'released')  # picked_qty(2) < planned(4)
        self.assertAlmostEqual(order.picked_qty, 2.0)
        # second batch: the remaining 2 units
        order.action_generate_picking(qty_this=2)
        p2 = (order.picking_ids - p1)
        self.assertAlmostEqual(p2.x_mes_order_qty, 2.0)
        self.assertAlmostEqual(p2.move_ids.product_uom_qty, 4.0)
        p2.move_ids.picked = True
        p2.button_validate()
        self.assertEqual(order.state, 'picked')
        self.assertAlmostEqual(order.picked_qty, 4.0)

    # --- F5 R2: batches may not exceed the order scope ---
    def test_17_over_pick_blocked(self):
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        order = self._make_order(mo, 4)
        with self.assertRaises(UserError):
            order.action_generate_picking(qty_this=5)

    # --- F5 R1 / D8: pre-issue materials are excluded from pickings ---
    def test_18_advance_issue_excluded(self):
        self._set_line_side()
        product = self.env['product.product'].create({'name': 'P-ADV', 'uom_id': self.uom_unit.id, 'default_code': 'DWG-MES-TEST', 'x_board_side': 'single'})
        comp_a = self.env['product.product'].create({'name': 'COMP-A', 'uom_id': self.uom_unit.id})
        comp_b = self.env['product.product'].create({'name': 'COMP-B', 'uom_id': self.uom_unit.id})
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_id': product.id,
            'product_uom_id': self.uom_unit.id,
            'product_qty': 1.0,
            'type': 'normal',
            'x_workshop_id': self.bom_workshop.id,
            'bom_line_ids': [
                (0, 0, {
                    'product_id': comp_a.id, 'product_qty': 2.0,
                    'product_uom_id': self.uom_unit.id, 'x_advance_issue': True,
                }),
                (0, 0, {
                    'product_id': comp_b.id, 'product_qty': 3.0,
                    'product_uom_id': self.uom_unit.id,
                }),
            ],
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 10, 'bom_id': bom.id,
            'company_id': self.company.id,
        })
        order = self._make_order(mo, 4)
        order.action_generate_picking()
        moves = order.picking_ids.move_ids
        self.assertEqual(moves.mapped('product_id'), comp_b, 'only the non-pre-issue component moves')
        self.assertAlmostEqual(moves.product_uom_qty, 12.0)  # 3 * 4 units

    # ===== F4: replenishment suggestions (架构设计 3.4) =====

    def test_19_replenishment_requires_bom(self):
        mo = self._make_mo(10)
        with self.assertRaises(UserError):
            mo.action_generate_replenishment()

    def test_20_replenishment_creates_rfq_for_shortfall(self):
        mo = self._make_bom_mo(qty=10)  # component demand = 2 * 10 = 20
        component = mo.bom_id.bom_line_ids.product_id
        component.route_ids = [(6, 0, [self.env.ref('purchase_stock.route_warehouse0_buy').id])]
        vendor = self.env['res.partner'].create({'name': 'V-MES'})
        component.seller_ids = [(0, 0, {
            'partner_id': vendor.id,
            'price': 1.0,
            'product_uom_id': self.uom_unit.id,
        })]
        mo.action_generate_replenishment()
        self.assertTrue(mo.x_last_replenishment_date, 'the run must be stamped on the MO')
        po = self.env['purchase.order'].search([('origin', '=', mo.name)])
        self.assertTrue(po, 'an RFQ must be created for the shortage')
        self.assertEqual(po.order_line.product_id, component)
        self.assertAlmostEqual(po.order_line.product_qty, 20.0)
        self.assertIn(po, mo.x_replenishment_po_ids)

    def test_21_replenishment_skips_stocked_component(self):
        mo = self._make_bom_mo(qty=10)
        component = mo.bom_id.bom_line_ids.product_id
        warehouse = mo.picking_type_id.warehouse_id
        self.env['stock.quant'].create({
            'product_id': component.id,
            'location_id': warehouse.lot_stock_id.id,
            'quantity': 50.0,
        })
        component.invalidate_recordset(['free_qty'])
        mo.action_generate_replenishment()
        po = self.env['purchase.order'].search([('origin', '=', mo.name)])
        self.assertFalse(po, 'enough on hand -> no replenishment suggestion')

    def test_22_replenishment_counts_in_transit(self):
        """Confirmed purchase in transit covers the demand -> no suggestion."""
        mo = self._make_bom_mo(qty=10)  # component demand = 2 * 10 = 20
        component = mo.bom_id.bom_line_ids.product_id
        component.route_ids = [(6, 0, [self.env.ref('purchase_stock.route_warehouse0_buy').id])]
        vendor = self.env['res.partner'].create({'name': 'V-TRANSIT'})
        component.seller_ids = [(0, 0, {
            'partner_id': vendor.id, 'price': 1.0,
            'product_uom_id': self.uom_unit.id,
        })]
        po = self.env['purchase.order'].create({
            'partner_id': vendor.id,
            'order_line': [(0, 0, {
                'name': component.display_name,
                'product_id': component.id,
                'product_qty': 20.0,
                'product_uom_id': self.uom_unit.id,
                'price_unit': 1.0,
                'date_planned': fields.Datetime.now(),
            })],
        })
        po.button_confirm()
        component.invalidate_recordset(['virtual_available'])
        mo.action_generate_replenishment()
        extra = self.env['purchase.order'].search([('origin', '=', mo.name)])
        self.assertFalse(extra, 'in-transit qty covers the demand -> no extra suggestion')

    def test_23_replenishment_does_not_double_count_own_demand(self):
        """A confirmed MO's own component demand must not shrink its forecast."""
        mo = self._make_bom_mo(qty=10)  # component demand = 20
        component = mo.bom_id.bom_line_ids.product_id
        warehouse = mo.picking_type_id.warehouse_id
        self.env['stock.quant'].create({
            'product_id': component.id,
            'location_id': warehouse.lot_stock_id.id,
            'quantity': 30.0,  # more than enough for this MO alone
        })
        mo.action_confirm()  # raw moves become outgoing demand of this very MO
        component.invalidate_recordset(['virtual_available'])
        mo.action_generate_replenishment()
        po = self.env['purchase.order'].search([('origin', '=', mo.name)])
        self.assertFalse(po, 'own demand must be added back, not counted twice')

    # --- online (上线) lives on the MES orders, not on the MO ---
    def test_23_online_lives_on_mes_orders(self):
        mo = self._make_mo(1000)
        order = self._make_order(mo, 100)
        self.assertFalse(mo._has_online_mes_order(), 'nothing online yet')
        onlined = mo._action_online_mes_orders()
        self.assertEqual(order, onlined)
        self.assertTrue(order.x_online_date, 'the MES order must be online')
        self.assertEqual(order.state, 'in_progress', 'online moves released to in_progress')
        self.assertIn(mo, mo._has_online_mes_order())

    def test_24_force_close_revokes_and_closes(self):
        """强制关闭: released MES orders revoked, MO closed, no backorder."""
        mo = self._make_bom_mo(qty=10)
        mo.action_confirm()
        order = self._make_order(mo, 4)
        self.assertEqual(order.state, 'released')
        mo.action_force_close()
        # zero-output abandonment ends as 'cancel' (state is derived from the
        # moves); anything actually produced would end as 'done'
        self.assertIn(mo.state, ('done', 'cancel'))
        self.assertEqual(order.state, 'cancelled')
        self.assertAlmostEqual(mo.x_mes_scheduled_qty, 0.0)
        self.assertEqual(mo.x_mes_schedule_state, 'unplanned')
        leftovers = (mo.move_raw_ids | mo.move_finished_ids).filtered(
            lambda m: m.state not in ('done', 'cancel'))
        self.assertFalse(leftovers, 'no backorder moves may survive')

    def test_25_mo_cancel_cascades_to_mes_orders(self):
        """Cancelling the MO revokes its still-released MES orders."""
        mo = self._make_bom_mo(qty=10)
        mo.action_confirm()
        order = self._make_order(mo, 4)
        mo.action_cancel()
        self.assertEqual(mo.state, 'cancel')
        self.assertEqual(order.state, 'cancelled')
        self.assertAlmostEqual(mo.x_mes_scheduled_qty, 0.0)

    # ------------------------------------------------------------------
    # station passing by work center (过站) + execution quantities
    # ------------------------------------------------------------------
    def _make_workcenter(self, operation, line=False, workshop=False):
        return self.env['mrp.workcenter'].create({
            'name': 'WC-%s' % (operation.code or operation.name),
            'x_workshop_id': (workshop or self.workshop).id,
            'x_operation_id': operation.id,
            'x_production_line_id': line.id if line else False,
        })

    def _make_online_order(self, qty=4, mode='station'):
        mo = self._make_mo(qty=10)
        order = self._make_order(mo, qty)
        if mode != 'station':
            order.x_manage_mode = mode
        order.action_online()
        return order

    def _leave_ng(self, order, serial):
        """NG leave; sn_wsd_quality (when installed) makes a defect code
        mandatory, so pass one in that case."""
        kwargs = {}
        if 'sn.wsd.quality.defect.code' in self.env:
            DefectCode = self.env['sn.wsd.quality.defect.code']
            defect = DefectCode.search(
                [('company_id', 'in', [order.company_id.id, False])], limit=1)
            if not defect:
                defect = DefectCode.create({
                    'name': 'Test NG', 'code': 'TNG',
                    'category': 'other', 'severity': 'minor',
                })
            kwargs['ng_defect'] = defect
        order.leave_station(serial, 'ng', **kwargs)
        return kwargs.get('ng_defect', False)

    def test_30_scan_enter_counts_input_on_entry(self):
        """Feeding an SN at the start work center counts input immediately,
        carries the work center onto the WIP row and bumps op counters."""
        order = self._make_online_order()
        wc_in = self._make_workcenter(self.op_in, line=self.line)
        serial = order.scan_enter('SN-STA-001', wc_in)
        self.assertEqual(serial.name, 'SN-STA-001')
        wip = self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', serial.id)])
        self.assertEqual(wip.route_operation_id.operation_id, self.op_in)
        self.assertEqual(wip.workcenter_id, wc_in)
        self.assertEqual(order.x_input_qty, 1.0)
        self.assertEqual(order.x_workorder_input_qty, 1.0)
        self.assertEqual(order.x_output_qty, 0.0)
        op_row = order.x_mes_route_id.x_daily_input_operation_id
        self.assertEqual((op_row.x_wip_qty, op_row.x_ok_qty, op_row.x_ng_qty), (1, 0, 0))
        self.assertFalse(order.leave_station(serial, 'ok'))
        self.assertEqual((op_row.x_wip_qty, op_row.x_ok_qty), (0, 1))

    def test_31_exit_operation_finishes_and_seals(self):
        """Leaving the end operation finishes the SN and seals the order
        against re-feeding the same SN."""
        order = self._make_online_order()
        wc_in = self._make_workcenter(self.op_in, line=self.line)
        wc_out = self._make_workcenter(self.op_out, line=self.line)
        serial = order.scan_enter('SN-STA-002', wc_in)
        order.leave_station(serial, 'ok')
        order.scan_enter('SN-STA-002', wc_out)
        self.assertTrue(order.leave_station(serial, 'ok'))
        self.assertEqual(order.x_output_qty, 1.0)
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-STA-002', wc_in)

    def test_32_line_and_workshop_guards(self):
        """Start-operation work centers must share the order's line; every
        work center must share the order's workshop."""
        order = self._make_online_order()
        other_workshop = self.env['sn.mrp.workshop'].create(
            {'name': 'WS-X', 'code': 'WSX'})
        with self.assertRaises(ValidationError):
            order.scan_enter(
                'SN-STA-003',
                self._make_workcenter(self.op_in, workshop=other_workshop))
        other_line = self.env['sn.mrp.production.line'].create({
            'name': 'LB', 'workshop_id': self.workshop.id,
        })
        with self.assertRaises(ValidationError):
            order.scan_enter(
                'SN-STA-003', self._make_workcenter(self.op_in, line=other_line))

    def test_33_first_entry_rules(self):
        """Unknown SNs cannot join mid-route; known-but-never-fed SNs must
        start at a start operation."""
        order = self._make_online_order()
        wc_out = self._make_workcenter(self.op_out, line=self.line)
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-NEVER-SEEN', wc_out)
        serial = self.env['sn.wsd.serial.identity'].create(
            {'name': 'SN-STA-004'})
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-STA-004', wc_out)

    def test_34_report_mode_quantities(self):
        """Report-mode quantities read the reported amounts at the counter
        operations; successors unlock once the plan quantity is reached."""
        order = self._make_online_order(qty=4, mode='report')
        op_in_row = order.x_mes_route_id.x_daily_input_operation_id
        op_out_row = order.x_mes_route_id.x_daily_output_operation_id
        order.report_operation_qty(op_in_row, 3)
        self.assertEqual(order.x_input_qty, 3.0)
        self.assertEqual(op_in_row.x_reported_qty, 3.0)
        with self.assertRaises(ValidationError):
            order.report_operation_qty(op_out_row, 1)
        order.report_operation_qty(op_in_row, 1)
        order.report_operation_qty(op_out_row, 2)
        self.assertEqual(order.x_output_qty, 2.0)

    def test_44_report_quota_scrap_and_completion(self):
        """Quota rule (OK+scrap consume, NG is a statistic, the whole batch
        fits the remainder), scrap generates a native scrap order, and the
        completion formula is OK + scrap >= plan."""
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        order = self._make_order(mo, 4)
        order.x_manage_mode = 'report'
        order.action_online()
        op_in_row = order.x_mes_route_id.x_daily_input_operation_id
        op_out_row = order.x_mes_route_id.x_daily_output_operation_id
        component, line_side = self._stock_line_side(order)
        # batch OK 3 + NG 1 -> effective 3, remainder 1
        order.report_operation_qty(op_in_row, 3, 1)
        self.assertEqual(op_in_row.x_reported_ng_qty, 1.0)
        # OK 2 more exceeds the remainder of 1
        with self.assertRaises(ValidationError):
            order.report_operation_qty(op_in_row, 2)
        # NG-only batch is still capped by the physical board count
        with self.assertRaises(ValidationError):
            order.report_operation_qty(op_in_row, 0, 2)
        # scrap 1: native scrap order per component, validated, quota closed
        reason = self.env['sn.wsd.scrap.reason'].search([], limit=1)
        order.report_operation_qty(op_in_row, 0, 0, 1, scrap_reason=reason)
        scrap = self.env['stock.scrap'].search([('origin', '=', order.name)])
        self.assertEqual(len(scrap), 1)
        self.assertEqual(scrap.scrap_qty, 2.0)  # BOM: 2 components per unit
        self.assertEqual(scrap.state, 'done')
        self.assertEqual(scrap.x_scrap_reason_id, reason)
        self.assertEqual(scrap.location_id, line_side)
        quant = self.env['stock.quant'].search([
            ('product_id', '=', component.id), ('location_id', '=', line_side.id)])
        self.assertEqual(quant.quantity, 98.0)
        # input op complete (3 OK + 1 scrap >= 4) -> output reportable
        order.report_operation_qty(op_out_row, 4)
        self.assertEqual(order.x_output_qty, 4.0)
        # invested amount counts NG: 3 + 1 + 1 = 5
        self.assertEqual(order.x_input_qty, 5.0)

    # ------------------------------------------------------------------
    # completion (完工入库): backflush + receipt + closure
    # ------------------------------------------------------------------
    def _done_workcenters(self):
        return (
            self._make_workcenter(self.op_in, line=self.line),
            self._make_workcenter(self.op_out, line=self.line),
        )

    def _order_with_output(self):
        """One online station-mode order with a single SN walked through
        both operations (output quantity = 1)."""
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        order = self._make_order(mo, 4)
        order.action_online()
        wc_in, wc_out = self._done_workcenters()
        serial = order.scan_enter('SN-DONE-001', wc_in)
        order.leave_station(serial, 'ok')
        order.scan_enter('SN-DONE-001', wc_out)
        order.leave_station(serial, 'ok')
        self.assertEqual(order.x_output_qty, 1.0)
        return order

    def _stock_line_side(self, order, qty=100):
        component = order.production_id.bom_id.bom_line_ids.product_id
        if not component.is_storable:
            component.is_storable = True
        line_side = order.production_line_id.workshop_id.component_location_id
        Quant = self.env['stock.quant']
        if not Quant.search([('product_id', '=', component.id),
                             ('location_id', '=', line_side.id)]):
            Quant.create({'product_id': component.id,
                          'location_id': line_side.id, 'quantity': qty})
        return component, line_side

    def test_40_complete_to_stock_waits_for_validation(self):
        order = self._order_with_output()
        component, line_side = self._stock_line_side(order)
        order.action_complete(1.0, 'stock')
        receipt = order.picking_ids.filtered(
            lambda p: p.state not in ('cancel',))
        self.assertEqual(len(receipt), 1)
        self.assertNotEqual(receipt.state, 'done')
        self.assertEqual(receipt.x_mes_order_qty, 1.0)
        self.assertEqual(order.x_done_qty, 1.0)
        self.assertEqual(order.state, 'done')
        self.assertEqual(order.production_id.state, 'done')
        # backflush consumed 2 components per finished unit
        quant = self.env['stock.quant'].search([
            ('product_id', '=', component.id), ('location_id', '=', line_side.id)])
        self.assertEqual(quant.quantity, 98.0)

    def test_41_complete_to_lineside_autovalidates(self):
        order = self._order_with_output()
        self._stock_line_side(order)
        wh = order.production_id.picking_type_id.warehouse_id
        workshop2 = self.env['sn.mrp.workshop'].create(
            {'name': 'WS-ZJ', 'code': 'WSZJ'})
        workshop2.component_location_id = self.env['stock.location'].create({
            'name': 'ZJ-LINE-SIDE', 'usage': 'internal',
            'location_id': wh.lot_stock_id.location_id.id,
        }).id
        order.action_complete(1.0, 'lineside', workshop=workshop2)
        receipt = order.picking_ids.filtered(lambda p: p.state not in ('cancel',))
        self.assertEqual(receipt.state, 'done')
        self.assertEqual(receipt.location_dest_id, workshop2.component_location_id)
        finished = order.production_id.product_id
        if finished.is_storable:
            quant = self.env['stock.quant'].search([
                ('product_id', '=', finished.id),
                ('location_id', '=', workshop2.component_location_id.id)])
            self.assertEqual(quant.quantity, 1.0)
        self.assertEqual(order.state, 'done')

    def test_42_backflush_shortage_blocks_completion(self):
        order = self._order_with_output()
        # stockable component, no stock at all on the line side -> the
        # backflush must fail and roll the whole completion back
        # (the negative-stock guard is opt-in during tests via its context key)
        component = order.production_id.bom_id.bom_line_ids.product_id
        if not component.is_storable:
            component.is_storable = True
        with self.assertRaises(ValidationError):
            order.with_context(test_stock_no_negative=True).action_complete(1.0, 'stock')
        self.env.flush_all()
        order.invalidate_recordset()
        self.assertEqual(order.x_done_qty, 0.0)
        self.assertEqual(order.state, 'in_progress')
        self.assertFalse(order.picking_ids.filtered(
            lambda p: p.state not in ('cancel',)))

    def test_43_complete_without_bom_blocked(self):
        """No BoM on the MO -> completion must fail hard (scheduling always
        provides one; a BOM-less order must never complete silently)."""
        order = self._make_online_order()  # _make_mo fixture has no BoM
        with self.assertRaises(ValidationError):
            order.action_complete(1.0, 'stock')
        order.invalidate_recordset()
        self.assertEqual(order.x_done_qty, 0.0)
        self.assertEqual(order.state, 'in_progress')
        self.assertFalse(order.picking_ids.filtered(
            lambda p: p.state not in ('cancel',)))

    def test_46_sn_bound_until_produced(self):
        """Single-binding: an NG or mid-flow SN cannot escape to another
        order; only producing (end op OK) releases it."""
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        order_a = self._make_order(mo, 4)
        order_a.action_online()
        order_b = self._make_order(mo, 4)
        order_b.action_online()
        wc_in, wc_out = self._done_workcenters()
        serial = order_a.scan_enter('SN-BIND-001', wc_in)
        self._leave_ng(order_a, serial)
        # NG on A, not produced there -> cannot enter B
        with self.assertRaises(ValidationError):
            order_b.scan_enter('SN-BIND-001', wc_in)
        # a healthy board produced through the end operation is released
        serial2 = order_a.scan_enter('SN-BIND-002', wc_in)
        order_a.leave_station(serial2, 'ok')
        order_a.scan_enter('SN-BIND-002', wc_out)
        order_a.leave_station(serial2, 'ok')
        serial2_b = order_b.scan_enter('SN-BIND-002', wc_in)
        self.assertTrue(serial2_b)

    def test_47_station_scan_routing(self):
        """Line-bound stations only bring their own line's orders; the scan
        router switches orders, expands WIP and feeds the selected order."""
        self._set_line_side()
        other_line = self.env['sn.mrp.production.line'].create({
            'name': 'LB2', 'workshop_id': self.workshop.id,
        })
        mo = self._make_bom_mo(qty=10)
        order_a = self._make_order(mo, 4)                 # line LA
        order_a.action_online()
        order_b = self._make_order(mo, 4, line=other_line)  # line LB2
        order_b.action_online()
        wc_in, _wc_out = self._done_workcenters()  # bound to LA
        Station = self.env['sn.wsd.mes.order']
        data = Station.sn_station_floor_data(wc_in.id)
        self.assertEqual([o['name'] for o in data['orders']], [order_a.name])
        # order barcode switches nothing here (B is another line, not listed)
        # feed a new SN through the scan router
        result = Station.sn_station_scan(wc_in.id, 'SN-SCAN-001', order_a.id)
        self.assertEqual(result['action'], 'entered')
        self.assertEqual(order_a.x_input_qty, 1.0)
        # scanning that WIP SN returns the leave action
        result = Station.sn_station_scan(wc_in.id, 'SN-SCAN-001')
        self.assertEqual(result['action'], 'leave')
        self.assertEqual(result['order_id'], order_a.id)
        # an unknown SN without a selected order is refused
        with self.assertRaises(ValidationError):
            Station.sn_station_scan(wc_in.id, 'SN-NOWHERE')
        # scanning the order barcode switches the current order
        result = Station.sn_station_scan(wc_in.id, order_a.name)
        self.assertEqual(result['action'], 'select_order')

    def test_48_online_offline_log(self):
        """Going online/offline keeps a who/when log; offline is blocked
        while boards are still in progress."""
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        order = self._make_order(mo, 4)
        order.action_online()
        log = order.x_online_log_ids
        self.assertEqual(len(log), 1)
        self.assertEqual(log.action, 'online')
        self.assertEqual(log.user_id, self.env.user)
        wc_in, wc_out = self._done_workcenters()
        serial = order.scan_enter('SN-LOG-001', wc_in)
        # a board in progress does NOT block going offline: feeding new SNs
        # is what online gates, the flow itself keeps running
        order.action_offline()
        self.assertFalse(order.x_online_date)
        # feeding a new SN into the start operation is refused offline
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-LOG-002', wc_in)
        # the in-progress board keeps flowing: it leaves and re-enters fine
        order.leave_station(serial, 'ok')
        order.scan_enter('SN-LOG-001', wc_out)
        order.leave_station(serial, 'ok')  # produced through the end op
        self.assertEqual(order.x_online_log_ids.mapped('action'),
                         ['offline', 'online'])

    def test_45_station_leave_scrap(self):
        """Station mode: leaving with result Scrap is terminal -- the SN is
        sealed, components are scrapped through a native scrap order."""
        self._set_line_side()
        mo = self._make_bom_mo(qty=10)
        order = self._make_order(mo, 8)
        order.action_online()
        wc_in, _wc_out = self._done_workcenters()
        self._stock_line_side(order)
        serial = order.scan_enter('SN-SCRAP-001', wc_in)
        reason = self.env['sn.wsd.scrap.reason'].search([], limit=1)
        with self.assertRaises(ValidationError):
            order.leave_station(serial, 'scrap')  # reason is mandatory
        order.leave_station(serial, 'scrap', scrap_reason=reason)
        op_row = order.x_mes_route_id.x_daily_input_operation_id
        self.assertEqual(op_row.x_scrap_qty, 1.0)
        self.assertEqual(op_row.x_ng_qty, 0)
        # yield counts the scrapped board
        self.assertAlmostEqual(op_row.x_yield_rate, 0.0)
        scrap = self.env['stock.scrap'].search([('origin', '=', order.name)])
        self.assertEqual(len(scrap), 1)
        self.assertEqual(scrap.scrap_qty, 2.0)  # BOM: 2 components per unit
        self.assertEqual(scrap.state, 'done')
        # the scrapped SN is sealed for this order
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-SCRAP-001', wc_in)

    # ------------------------------------------------------------------
    # NG re-pass: re-entry rules + retry limit (x_max_test_count)
    # ------------------------------------------------------------------
    def _ng_pass(self, order, wc, sn_name):
        serial = order.scan_enter(sn_name, wc)
        self._leave_ng(order, serial)
        return serial

    def test_49_pass_cap_counts_ok_and_ng(self):
        """The pass cap counts every pass (OK and NG alike): cap 2 allows
        two passes and blocks the third; an OK pass no longer seals the
        operation (mid-route ops only)."""
        order = self._make_online_order()
        wc_in = self._make_workcenter(self.op_in, line=self.line)
        self.op_in.x_max_test_count = 3
        self._ng_pass(order, wc_in, 'SN-NG-001')
        serial = order.scan_enter('SN-NG-001', wc_in)
        order.leave_station(serial, 'ok')
        serial = order.scan_enter('SN-NG-001', wc_in)  # ok row does not seal
        order.leave_station(serial, 'ok')
        with self.assertRaises(ValidationError):
            self._ng_pass(order, wc_in, 'SN-NG-001')  # 4th pass blocked

    def test_49b_cap_must_be_at_least_one(self):
        """Max test count is required and must be >= 1 (0 = unlimited was
        dropped); no context marker may bypass the cap anymore."""
        order = self._make_online_order()
        wc_in = self._make_workcenter(self.op_in, line=self.line)
        self.op_in.x_max_test_count = 1
        self._ng_pass(order, wc_in, 'SN-NG-003')
        with self.assertRaises(ValidationError):
            self._ng_pass(order, wc_in, 'SN-NG-003')  # cap 1 used
        with self.assertRaises(ValidationError):
            self.op_in.x_max_test_count = 0

    def test_49c_history_rows_coexist_many_ok(self):
        """Multiple ng and ok rows may coexist per (SN, operation) — the
        one-ok-row partial index is gone."""
        order = self._make_online_order()
        wc_in = self._make_workcenter(self.op_in, line=self.line)
        self.op_in.x_max_test_count = 3
        serial = order.scan_enter('SN-NG-004', wc_in)
        self._leave_ng(order, serial)
        serial = order.scan_enter('SN-NG-004', wc_in)
        order.leave_station(serial, 'ok')
        serial = order.scan_enter('SN-NG-004', wc_in)
        order.leave_station(serial, 'ok')
        rows = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', serial.id),
            ('route_operation_id.operation_id', '=', self.op_in.id),
        ])
        self.assertEqual(sorted(rows.mapped('result')), ['ng', 'ok', 'ok'])
