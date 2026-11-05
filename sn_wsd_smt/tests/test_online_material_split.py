from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOnlineMaterialSplit(TransactionCase):
    """制令单上线按 图号+面别 匹配 SMT 料站表拆行生成在线料表
    （smt-loading：工艺类型标识与制令单上线拆行）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-SPLIT', 'code': 'WSSP'})
        cls.line = cls.env['sn.mrp.production.line'].create(
            {'name': 'SPLIT', 'code': 'SPL', 'workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({'name': 'SP IN', 'code': 'SPIN'})
        cls.op_out = Operation.create({'name': 'SP OUT', 'code': 'SPOUT'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-SPLIT', 'code': 'RTSPL',
                'x_workshop_id': cls.workshop.id,
                'x_process_type': 'smt', 'state': 'confirmed',
                'x_production_side': 'single',
                'route_operation_ids': [
                    (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10,
                            'x_allow_entry': True}),
                    (0, 0, {'operation_id': cls.op_out.id, 'sequence': 20,
                            'x_allow_exit': True}),
                ],
                'x_daily_input_operation_id': cls.op_in.id,
                'x_daily_output_operation_id': cls.op_out.id,
                'x_workorder_input_operation_id': cls.op_in.id,
            })
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-SPLIT'})
        # 无料站表对照：同一路线再绑一个图号（有路线、无料站表）
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-NOTAB'})

    def _make_online_order(self, drawing):
        product = self.env['product.product'].create({
            'name': 'P-%s' % drawing, 'uom_id': self.uom_unit.id,
            'default_code': drawing, 'x_board_side': 'single',
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 10,
            'company_id': self.company.id,
        })
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': 5,
        })
        # 上线硬闸脚手架（mes-picking-lifecycle R1）：占位领料单过闸
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(self.env, order)
        return order

    def test_online_splits_material_table_rows(self):
        # spec: smt-loading/spec/工艺类型标识与制令单上线拆行/正常拆行
        self.env['sn.smt.material.table'].create({
            'table_name': 'TBL-SPLIT', 'model_code': 'DWG-SPLIT',
            'product_side': 'single',
            'detail_ids': [
                (0, 0, {'device_seq': 1, 'table_no': 'T1', 'loadpoint': '01',
                        'item_code': 'ITEM-A', 'point_qty': 2,
                        'point_location': 'R1C1'}),
                (0, 0, {'device_seq': 1, 'table_no': 'T1', 'loadpoint': '02',
                        'item_code': 'ITEM-B', 'point_qty': 4,
                        'point_location': 'R1C2'}),
                (0, 0, {'device_seq': 2, 'table_no': 'T2', 'loadpoint': '01',
                        'item_code': 'ITEM-C', 'point_qty': 1,
                        'point_location': 'R2C1'}),
            ],
        })
        order = self._make_online_order('DWG-SPLIT')
        order.action_online()
        rows = order.x_smt_online_material_ids
        self.assertEqual(len(rows), 3)
        first = rows.filtered(lambda r: r.item_code == 'ITEM-A')
        self.assertEqual(len(first), 1)
        self.assertEqual(first.device_seq, 1)
        self.assertEqual(first.table_no, 'T1')
        self.assertEqual(first.loadpoint, '01')
        self.assertEqual(first.point_qty, 2)
        self.assertEqual(first.point_location, 'R1C1')

    def test_online_without_table_zero_rows_not_blocked(self):
        # spec: smt-loading/spec/工艺类型标识与制令单上线拆行/无料站表
        order = self._make_online_order('DWG-NOTAB')
        order.action_online()
        self.assertEqual(len(order.x_smt_online_material_ids), 0)
