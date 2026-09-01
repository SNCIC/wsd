from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick


@tagged('post_install', '-at_install')
class TestStockPackagePallet(TransactionCase):
    """pallet-receipt-offline：攒托开单是产后入账动作（产品过包装工序进
    箱即已产出），只要求制令单 in_progress——已下线（正常收尾盘托盘节
    奏）照常开单；未投产/已完结仍拦。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-PLT', 'code': 'WSPLT'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'PLT', 'code': 'PLT', 'workshop_id': cls.workshop.id})
        # BOM 车间与产线车间分离（多步仓库下 MO 源库位跟随 BOM 车间，
        # 同车间会让源=目的地），同 test_mes_order 的处理
        cls.bom_workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-PLT-BOM', 'code': 'WSPLTB'})
        wh = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        if wh and wh.manufacture_steps != 'mrp_one_step' and wh.pbm_loc_id:
            cls.bom_workshop.component_location_id = cls.env['stock.location'].create({
                'name': 'PLT-BOM-COMP', 'usage': 'internal',
                'location_id': wh.pbm_loc_id.id,
            }).id
        if wh and wh.manufacture_steps == 'pbm_sam' and wh.sam_loc_id:
            cls.bom_workshop.finished_product_location_id = cls.env['stock.location'].create({
                'name': 'PLT-BOM-FP', 'usage': 'internal',
                'location_id': wh.sam_loc_id.id,
            }).id
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-PLT', 'code': 'RTPLT',
                'x_workshop_id': cls.workshop.id,
            })
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'PLT-IN', 'code': 'PLTIN', 'x_station_type': 'assembly'})
        cls.op_out = Operation.create({
            'name': 'PLT-OUT', 'code': 'PLTOUT', 'x_station_type': 'final_test'})
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
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-PLT'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[1].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _make_bom_mo(self, qty=10):
        """BOM 支撑的 MO（单组件、每台 2 件）——完工收货要倒冲。"""
        product = self.env['product.product'].create({
            'name': 'P-PLT', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-PLT', 'x_board_side': 'single',
        })
        component = self.env['product.product'].create({
            'name': 'COMP-PLT', 'uom_id': self.uom_unit.id, 'is_storable': True,
        })
        self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_id': product.id,
            'product_uom_id': self.uom_unit.id,
            'product_qty': 1.0,
            'type': 'normal',
            'x_workshop_id': self.bom_workshop.id,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 2.0,
            })],
        })
        return self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': qty,
            'company_id': self.company.id,
        })

    def _make_order(self, mo, qty):
        return self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': qty,
        })

    def _make_workcenter(self, operation):
        return self.env['mrp.workcenter'].create({
            'name': 'WC-%s' % operation.code,
            'x_workshop_id': self.workshop.id,
            'x_operation_id': operation.id,
            'x_production_line_id': self.line.id,
        })

    def _order_with_output(self):
        """上线投产 + 1 台过完全部工序（产出=1），再备好线边料。"""
        self.workshop.component_location_id = self.env['stock.location'].create({
            'name': 'PLT-LINE-SIDE', 'usage': 'internal',
        }).id
        mo = self._make_bom_mo()
        order = self._make_order(mo, 4)
        give_pick(self.env, order)
        order.action_online()
        wc_in = self._make_workcenter(self.op_in)
        wc_out = self._make_workcenter(self.op_out)
        serial = order.scan_enter('SN-PLT-001', wc_in)
        order.leave_station(serial, 'ok')
        order.scan_enter('SN-PLT-001', wc_out)
        order.leave_station(serial, 'ok')
        self.assertEqual(order.x_output_qty, 1.0)
        component = mo.bom_id.bom_line_ids.product_id
        self.env['stock.quant'].create({
            'product_id': component.id,
            'location_id': self.workshop.component_location_id.id,
            'quantity': 100,
        })
        return order

    def _pack_and_close(self, order, carton_no, pallet_no):
        """装箱 → 绑托 → 关托（均为产后动作，无制令单门槛）。"""
        identity = self.env['sn.wsd.serial.identity'].create({
            'name': 'SN-PACK-%s' % carton_no})
        carton = self.env['stock.package'].get_or_create_wsd_package(
            carton_no, 'carton', self.company)
        self.env['sn.wsd.meter.pack.record'].create({
            'serial_identity_id': identity.id,
            'production_id': order.production_id.id,
            'carton_package_id': carton.id,
        })
        BindLog = self.env['sn.wsd.carton.pallet.binding.log']
        BindLog.bind_carton_to_pallet(pallet_no, carton_no)
        BindLog.close_pallet(pallet_no)
        return self.env['stock.package'].search([
            ('name', '=', pallet_no),
            ('x_wsd_company_id', '=', self.company.id),
            ('x_wsd_package_role', '=', 'pallet'),
        ], limit=1)

    # ------------------------------------------------------------------
    # 下线后收尾盘托盘：开单成功（口径变更的核心场景）
    # ------------------------------------------------------------------

    def test_01_receive_after_offline(self):
        order = self._order_with_output()
        order.action_offline()
        self.assertFalse(order.x_online_date, 'the order must be offline')
        self.assertEqual(order.state, 'in_progress',
                         'going offline must not change the lifecycle state')
        pallet = self._pack_and_close(order, 'CTN-PLT-1', 'PLT-0001')

        result = self.env['sn.wsd.carton.pallet.binding.log'].receive_pallets(
            ['PLT-0001'])

        self.assertTrue(result['ok'])
        self.assertEqual(len(result['receipts']), 1)
        self.assertEqual(result['receipts'][0]['qty'], 1)
        self.assertEqual(pallet.x_wsd_pack_state, 'received')
        self.assertEqual(order.x_done_qty, 1.0)
        self.assertEqual(order.state, 'done', 'full receipt closes the order')

    def test_02_released_order_blocked(self):
        mo = self._make_bom_mo()
        order = self._make_order(mo, 4)
        self.assertEqual(order.state, 'released')
        self._pack_and_close(order, 'CTN-PLT-2', 'PLT-0002')

        with self.assertRaises(ValidationError) as ctx:
            self.env['sn.wsd.carton.pallet.binding.log'].receive_pallets(
                ['PLT-0002'])

        self.assertIn('must be in progress to receive products',
                      str(ctx.exception))
        pallet = self.env['stock.package'].search([
            ('name', '=', 'PLT-0002'),
            ('x_wsd_company_id', '=', self.company.id),
            ('x_wsd_package_role', '=', 'pallet'),
        ], limit=1)
        self.assertNotEqual(pallet.x_wsd_pack_state, 'received',
                            'a rejected receive must leave the pallet untouched')
