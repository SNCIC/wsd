from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDrawingMaterialUnify(TransactionCase):
    """关键物料清单消费统一：SMT 单同样按清单拆行并门禁；与料站表双轨
    并行；整机物料行 usage_times 维持现状；没维护清单不管控。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_location = cls.wh.lot_stock_id
        cls.drawing_no = 'DWG-UNIFY-001'
        cls.product_fg = cls.env['product.product'].create({
            'name': 'Unify Finished Good',
            'default_code': cls.drawing_no,
            'is_storable': True,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Unify Material',
            'default_code': 'UNIFY-TST-A',
            'tracking': 'lot',
            'is_storable': True,
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'UNIFY-LOT-A',
            'product_id': cls.product.id,
            'company_id': cls.env.company.id,
        })
        cls.env['stock.quant'].create({
            'product_id': cls.product.id,
            'location_id': cls.stock_location.id,
            'lot_id': cls.lot.id,
            'quantity': 100.0,
        })
        cls.tooling_template = cls.env['sn.tooling.template'].create({
            'code': 'UNIFY-TL-T',
            'name': 'Unify Stencil',
            'type_id': cls.env['sn.tooling.type'].create({
                'name': 'Unify Stencil Type', 'code': 'UNIFY-ST'}).id,
        })
        cls.tooling = cls.env['sn.tooling'].create({
            'sn': 'UNIFY-TL-001', 'template_id': cls.tooling_template.id})
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'UNIFY WS'})
        cls.production_line = cls.env['sn.mrp.production.line'].create({
            'name': 'UNIFY LINE',
            'workshop_id': cls.workshop.id,
            'company_id': cls.env.company.id,
        })
        cls.op_print = cls.env['sn.wsd.operation'].create({'name': 'UNIFY Print'})
        cls.op_place = cls.env['sn.wsd.operation'].create({
            'name': 'UNIFY Place', 'x_max_test_count': 9})
        cls.op_asm = cls.env['sn.wsd.operation'].create({'name': 'UNIFY Asm'})
        cls.smt_route = cls._create_process_route('UNIFY-SMT-RT', 'smt')
        cls.machine_route = cls._create_process_route('UNIFY-MC-RT', 'machine')
        # SMT 贴片工序清单：1 制具；整机装配工序清单：1 物料（usage_times=2）
        cls.env['sn.wsd.drawing.material'].create({
            'workshop_id': cls.workshop.id,
            'x_drawing_no': cls.drawing_no,
            'operation_id': cls.op_place.id,
            'x_side': 'single',
            'line_ids': [(0, 0, {
                'material_ref': 'sn.tooling.template,%s' % cls.tooling_template.id,
                'usage_times': 1,
            })],
        })
        cls.env['sn.wsd.drawing.material'].create({
            'workshop_id': cls.workshop.id,
            'x_drawing_no': cls.drawing_no,
            'operation_id': cls.op_asm.id,
            'x_side': 'single',
            'line_ids': [(0, 0, {
                'material_ref': 'product.product,%s' % cls.product.id,
                'usage_times': 2,
            })],
        })
        cls.smt_order, cls.smt_rop_print, cls.smt_rop_place = cls._create_order_with_route(
            cls.smt_route, [(cls.op_print, 10), (cls.op_place, 20)])
        cls.smt_order.x_mes_route_id.x_material_operation_id = cls.smt_rop_place.id
        cls.machine_order, *machine_rops = cls._create_order_with_route(
            cls.machine_route, [(cls.op_asm, 10)])
        cls.machine_rop_asm = machine_rops[0]
        cls.identity = cls.env['sn.wsd.serial.identity'].create({
            'name': 'UNIFY-SN-001', 'origin_type': 'manual'})
        # 过站链：两站皆可进（首站），贴片为产出站
        cls.smt_rop_print.x_allow_entry = True
        cls.smt_rop_place.x_allow_entry = True
        cls.smt_order.x_online_date = fields.Datetime.now()
        cls.wc_print = cls.env['mrp.workcenter'].create({
            'name': 'UNIFY WC PRINT',
            'x_operation_id': cls.op_print.id,
            'x_production_line_id': cls.production_line.id,
            'x_workshop_id': cls.workshop.id,
        })
        cls.wc_place = cls.env['mrp.workcenter'].create({
            'name': 'UNIFY WC PLACE',
            'x_operation_id': cls.op_place.id,
            'x_production_line_id': cls.production_line.id,
            'x_workshop_id': cls.workshop.id,
        })
        cls.defect_code = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'Unify NG', 'code': 'UNIFY-NG',
            'category': 'other', 'severity': 'minor',
        })

    @classmethod
    def _create_process_route(cls, code, process_type):
        return cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': code,
                'code': code,
                'x_process_type': process_type,
                'x_workshop_id': cls.workshop.id,
            })

    @classmethod
    def _create_order_with_route(cls, process_route, op_sequence):
        MesOrder = cls.env['sn.wsd.mes.order']
        production = cls.env['mrp.production'].create({
            'product_id': cls.product_fg.id,
            'product_qty': 10,
        })
        with patch.object(type(MesOrder), '_setup_route', lambda self: True):
            order = MesOrder.create({
                'production_id': production.id,
                'production_line_id': cls.production_line.id,
                'x_workshop_id': cls.workshop.id,
                'date_plan': fields.Date.today(),
                'planned_qty': 10,
            })
        private_route = cls.env['sn.wsd.mes.order.route'].create({
            'mes_order_id': order.id,
            'route_id': process_route.id,
        })
        order.x_mes_route_id = private_route.id
        rops = []
        for operation, sequence in op_sequence:
            rops.append(cls.env['sn.wsd.mes.order.route.operation'].create({
                'mes_route_id': private_route.id,
                'operation_id': operation.id,
                'sequence': sequence,
            }))
        return (order, *rops)

    def _consume(self, order, route_operation, identity=None):
        return self.env['sn.smt.material.consumption'].consume_for_serial(
            route_operation, identity=identity or self.identity)

    # ------------------------------------------------------------------
    # SMT 单拆行 + 门禁 + 双轨
    # ------------------------------------------------------------------

    def test_smt_order_splits_drawing_rows_and_gates(self):
        self.smt_order._prepare_drawing_online_materials()
        drawing_rows = self.smt_order.x_smt_online_material_ids.filtered(
            lambda line: line.source == 'drawing_list')
        self.assertEqual(len(drawing_rows), 1)
        self.assertEqual(drawing_rows.route_operation_id, self.smt_rop_place)
        # 制具未上线：贴片出站被门禁拦下
        with self.assertRaises(ValidationError):
            self._consume(self.smt_order, self.smt_rop_place)

    def test_smt_order_dual_track_with_material_table(self):
        online = self.env['sn.smt.online.material'].create({
            'mes_order_id': self.smt_order.id,
            'model_code': 'UNIFYTST',
            'device_seq': 1,
            'table_no': 'T1',
            'loadpoint': '25',
            'item_code': 'UNIFY-TST-A',
            'process_face': 'single',
            'point_qty': 4,
        })
        self.smt_order._prepare_drawing_online_materials()
        self.env['sn.smt.loading.service'].load_material(
            self.smt_order, self.env['mrp.workcenter'].create(
                {'name': 'UNIFY LOAD WC'}), '1.T1', '25', self.lot.name)
        self.env['sn.smt.loading.service'].load_drawing_barcode(
            self.smt_order, self.tooling.sn)
        self.assertEqual(online.loaded_material_lot_id, self.lot)
        # 贴片（物料关联工序）出站：料站表扣点，制具行只门禁不扣量
        created = self._consume(self.smt_order, self.smt_rop_place)
        self.assertEqual(len(created), 1)
        self.assertEqual(created.online_material_id, online)
        self.assertEqual(online.remaining_qty, 96.0)
        # 印刷（非关联工序）出站：不扣不拦
        other = self.env['sn.wsd.serial.identity'].create({
            'name': 'UNIFY-SN-002', 'origin_type': 'manual'})
        self.assertFalse(self._consume(self.smt_order, self.smt_rop_print, other))

    # ------------------------------------------------------------------
    # 整机物料行维持现状
    # ------------------------------------------------------------------

    def test_machine_order_material_row_unchanged(self):
        self.machine_order._prepare_drawing_online_materials()
        drawing_rows = self.machine_order.x_smt_online_material_ids.filtered(
            lambda line: line.source == 'drawing_list')
        self.assertEqual(len(drawing_rows), 1)
        self.env['sn.smt.loading.service'].load_drawing_barcode(
            self.machine_order, self.lot.name)
        created = self._consume(self.machine_order, self.machine_rop_asm)
        self.assertEqual(len(created), 1)
        self.assertEqual(created.consumed_qty, 2.0)
        self.assertEqual(created.material_lot_id, self.lot)
        self.assertEqual(drawing_rows.remaining_qty, 98.0)

    def test_no_list_no_control(self):
        bare_order, *bare_rops = self._create_order_with_route(
            self.machine_route, [(self.op_print, 10)])
        bare_rop = bare_rops[0]
        bare_order._prepare_drawing_online_materials()
        self.assertFalse(bare_order.x_smt_online_material_ids)
        self.assertFalse(self._consume(bare_order, bare_rop))

    # ------------------------------------------------------------------
    # 制具/辅料过站计数（出站工序==清单工序才计、按板计、NG 不计）
    # ------------------------------------------------------------------

    def _pass_station(self, wc, identity, result='ok'):
        self.smt_order.scan_enter(identity.name, wc)
        return self.smt_order.leave_station(
            identity, result, ng_defect=self.defect_code if result == 'ng' else False)

    def _load_tooling_online(self):
        self.smt_order._prepare_drawing_online_materials()
        self.env['sn.smt.loading.service'].load_drawing_barcode(
            self.smt_order, self.tooling.sn)

    def test_tooling_counted_per_board_at_its_operation(self):
        self._load_tooling_online()
        self._pass_station(self.wc_place, self.identity)
        self.assertEqual(self.tooling.total_usage_count, 1)
        self.assertEqual(self.tooling.cycle_usage_count, 1)
        # 第二块板过同一工序：按板计，再 +1（拼版口径同此，逐板各 +1）
        second = self.env['sn.wsd.serial.identity'].create({
            'name': 'UNIFY-SN-101', 'origin_type': 'manual'})
        self._pass_station(self.wc_place, second)
        self.assertEqual(self.tooling.total_usage_count, 2)

    def test_tooling_not_counted_at_other_operation(self):
        self._load_tooling_online()
        self._pass_station(self.wc_print, self.identity)
        self.assertEqual(self.tooling.total_usage_count, 0)

    def test_ng_leave_does_not_count_repass_ok_counts(self):
        self._load_tooling_online()
        self.smt_order.scan_enter(self.identity.name, self.wc_place)
        self.smt_order.leave_station(
            self.identity, 'ng', ng_defect=self.defect_code)
        self.assertEqual(self.tooling.total_usage_count, 0)
        # NG 免费重进：重过 OK 才计数
        self._pass_station(self.wc_place, self.identity)
        self.assertEqual(self.tooling.total_usage_count, 1)
