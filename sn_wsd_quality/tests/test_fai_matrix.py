from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFaiMatrix(TransactionCase):
    """FAI 过站检验矩阵（fai-inspection-matrix）：样本×检验项结果格。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-FAIM', 'code': 'WSFMTX'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LFAIM', 'code': 'LFAIM', 'workshop_id': cls.workshop.id,
        })
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-FAIM', 'usage': 'internal'}).id
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'FAIM-IN', 'code': 'MTXIN', 'x_station_type': 'assembly',
            'x_max_test_count': 3,
        })
        cls.op_out = Operation.create(
            {'name': 'FAIM-OUT', 'code': 'MTXOUT', 'x_station_type': 'final_test'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-FAIM', 'code': 'RTMTX', 'x_workshop_id': cls.workshop.id,
            })
        cls.route.write({
            'state': 'confirmed', 'x_production_side': 'single',
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
        ops = cls.route.route_operation_ids.sorted('sequence')
        ops[1].blocked_by_route_operation_ids = [(6, 0, ops[0].ids)]
        cls.env['sn.wsd.process.route.drawing'].create(
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-FAIM-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-FAIM', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-FAIM-TEST', 'x_board_side': 'single',
        })
        component = cls.env['product.product'].create({
            'name': 'COMP-FAIM', 'uom_id': cls.uom_unit.id, 'is_storable': True,
        })
        cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'product_id': cls.product.id,
            'product_uom_id': cls.uom_unit.id, 'product_qty': 1.0,
            'type': 'normal', 'x_workshop_id': cls.workshop.id,
            'bom_line_ids': [(0, 0, {'product_id': component.id,
                                      'product_qty': 2.0,
                                      'product_uom_id': cls.uom_unit.id})],
        })
        cls.mo = cls.env['mrp.production'].create({
            'product_id': cls.product.id, 'product_qty': 10,
            'company_id': cls.company.id,
        })
        cls.wc_in = cls.env['mrp.workcenter'].create({
            'name': 'WC-FAIM-IN', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id,
            'x_operation_id': cls.op_in.id,
        })
        # FAI 方案：首件工序=op_in，样本台数 2，两条检验行（数值+文本）
        # → 齐套自动展开 2 样本 × 2 项 = 4 格
        cls.scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'FAI MATRIX SCHEME', 'code': 'FAI-MTX-01',
            'inspection_type': 'fai', 'state': 'effective',
            'operation_id': cls.op_in.id,
            'sample_size': 2,
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [
                (0, 0, {'name': 'Voltage check', 'item_code': 'FAI-MTX-VLT',
                        'item_type': 'numeric', 'lower_limit': 10.0,
                        'upper_limit': 20.0}),
                (0, 0, {'name': 'BOM check', 'item_code': 'FAI-MTX-BOM',
                        'item_type': 'text', 'expected_value': 'OK'}),
            ],
        })
        cls.voltage_code = 'FAI-MTX-VLT'
        cls.bom_code = 'FAI-MTX-BOM'

    def _order(self, qty=8):
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': self.mo.id, 'production_line_id': self.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': qty,
        })
        # 上线硬闸（mes-picking-lifecycle）：占位领料单过闸后取消
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        return order

    def _feed(self, order, name):
        return order.scan_enter(name, self.wc_in)

    def _ready_samples(self, order, prefix):
        # 把 2 台样本送到检并出站 OK → 样本齐套（矩阵在此展开）
        serials = []
        for n in ('101', '102'):
            serial = self._feed(order, '%s-%s' % (prefix, n))
            order.leave_station(serial, 'ok')
            serials.append(serial)
        return serials

    def _line(self, inspection, code):
        return inspection.line_ids.filtered(
            lambda l: l.item_code == code)[:1]

    def _cell(self, inspection, code, serial):
        return inspection.cell_ids.filtered(
            lambda c: c.line_id == self._line(inspection, code)
            and c.serial_identity_id == serial)[:1]

    # ---------------- 到检展开矩阵（默认 OK） ----------------
    def test_10_full_sample_set_expands_matrix(self):
        # 到检自动展开 N×M 格且默认合格（异常驱动：检验员只改异常格）
        order = self._order()
        s1, s2 = self._ready_samples(order, 'SN-MTX-A')
        inspection = order.x_fai_inspection_id
        self.assertEqual(len(inspection.cell_ids), 4,
                         'full sample set expands N x M cells')
        self.assertEqual(set(inspection.cell_ids.mapped('result')),
                         {'pass'}, 'fresh cells default to pass')
        self.assertEqual(set(inspection.line_ids.mapped('result')),
                         {'pass'}, 'item lines derive pass from default cells')
        numeric = self._cell(inspection, self.voltage_code, s1)
        self.assertEqual(numeric.measured_value, 15.0,
                         'numeric cells are pre-filled with the range midpoint')
        text = self._cell(inspection, self.bom_code, s1)
        self.assertEqual(text.text_value, 'OK',
                         'text cells are pre-filled with the expected value')
        for line in inspection.line_ids:
            self.assertEqual(len(line.cell_ids), 2,
                             'each item line carries one cell per sample')
        for serial in (s1, s2):
            self.assertEqual(len(inspection.cell_ids.filtered(
                lambda c: c.serial_identity_id == serial)), 2,
                'each sample carries one cell per item line')
        # 幂等：重复触发不重建
        inspection._fai_expand_result_cells()
        self.assertEqual(len(inspection.cell_ids), 4,
                         're-running the expansion does not duplicate cells')

    # ---------------- 逐格录入与派生 ----------------
    def test_20_cell_entry_derives_line_and_document(self):
        # 数值格比对上下限自动判；任一格 fail → line fail；全 pass → pass
        order = self._order()
        s1, s2 = self._ready_samples(order, 'SN-MTX-B')
        inspection = order.x_fai_inspection_id
        voltage = self._line(inspection, self.voltage_code)
        bom = self._line(inspection, self.bom_code)
        cell_s1 = self._cell(inspection, self.voltage_code, s1)
        cell_s2 = self._cell(inspection, self.voltage_code, s2)
        # 先判其余格：s2 数值格落区间内 → pass；文本格记 NG → fail
        cell_s2.write({'measured_value': 15.0})
        self.assertEqual(cell_s2.result, 'pass',
                         'an in-range measurement passes the cell')
        for serial in (s1, s2):
            self._cell(inspection, self.bom_code, serial).write(
                {'text_value': 'NG', 'manual_result': 'fail'})
        self.assertEqual(bom.result, 'fail',
                         'any failing cell fails the item line')
        # 一格超上限 → 该格 fail、对应 line fail、单据 fail
        cell_s1.write({'measured_value': 25.0})
        self.assertEqual(cell_s1.result, 'fail',
                         'a value over the upper limit fails the cell')
        self.assertEqual(voltage.result, 'fail',
                         'one failing cell fails the whole item line')
        self.assertEqual(inspection.result, 'fail',
                         'with every line failing the inspection fails')
        # 改回区间内 → 该格 pass、line 全 pass 派生为 pass
        cell_s1.write({'measured_value': 12.0})
        self.assertEqual(cell_s1.result, 'pass',
                         'a back-in-range value passes the cell')
        self.assertEqual(voltage.result, 'pass',
                         'all cells passing passes the item line')

    # ---------------- 任一格 fail 整轮判退 ----------------
    def test_30_any_cell_fail_reopens_round(self):
        # 唯一一格 fail + done → 整轮判退开新一轮；上一轮格留痕
        order = self._order()
        s1, s2 = self._ready_samples(order, 'SN-MTX-C')
        inspection = order.x_fai_inspection_id
        self._cell(inspection, self.voltage_code, s1).write(
            {'measured_value': 25.0})  # 超上限：唯一 fail 格
        self._cell(inspection, self.voltage_code, s2).write(
            {'measured_value': 15.0})
        for serial in (s1, s2):
            self._cell(inspection, self.bom_code, serial).write(
                {'text_value': 'OK', 'manual_result': 'pass'})
        inspection.action_done()
        self.assertEqual(inspection.state, 'done')
        self.assertNotEqual(inspection.result, 'pass')  # fail/partial 皆判退
        self.assertEqual(order.x_fai_state, 'in_progress')
        self.assertEqual(order.x_fai_round, 2)
        new = order.x_fai_inspection_id
        self.assertNotEqual(new, inspection)
        self.assertEqual(new.state, 'open')
        self.assertFalse(new.x_fai_serial_ids)
        self.assertFalse(new.cell_ids,
                         'the new round waits for fresh samples')
        # 上一轮 N×M 格原样留痕
        self.assertEqual(len(inspection.cell_ids), 4,
                         'previous round cells stay for audit')

    # ---------------- 一键全部合格（格级） ----------------
    def test_40_set_all_pass_fills_cells_and_unlocks(self):
        order = self._order()
        self._ready_samples(order, 'SN-MTX-D')
        inspection = order.x_fai_inspection_id
        with self.assertRaises(ValidationError):
            self._feed(order, 'SN-MTX-D-103')  # 样本满 2 且未判定：拦
        inspection.action_set_all_pass()
        self.assertEqual(set(inspection.cell_ids.mapped('result')),
                         {'pass'}, 'set-all-pass judges every cell')
        for cell in inspection.cell_ids.filtered(
                lambda c: c.line_id.item_code == self.voltage_code):
            self.assertEqual(cell.measured_value, 15.0,
                             'numeric cells get the mid-range pass value')
        self.assertEqual(set(inspection.line_ids.mapped('result')),
                         {'pass'}, 'item lines derive from the judged cells')
        inspection.action_done()
        self.assertEqual(inspection.result, 'pass')
        self.assertEqual(order.x_fai_state, 'passed')
        self._feed(order, 'SN-MTX-D-103')  # 投入解锁

    # ---------------- 唯一约束 ----------------
    def test_50_duplicate_sn_item_cell_blocked(self):
        # 同 SN 同项第二格：唯一约束拦截（savepoint 包裹，仿 ipqc 写法）
        order = self._order()
        s1, s2 = self._ready_samples(order, 'SN-MTX-E')
        inspection = order.x_fai_inspection_id
        Cell = self.env['sn.wsd.quality.inspection.cell']
        cell = self._cell(inspection, self.voltage_code, s1)
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                Cell.create({
                    'inspection_id': inspection.id,
                    'serial_identity_id': s1.id,
                    'line_id': cell.line_id.id,
                })
        self.assertEqual(len(inspection.cell_ids), 4,
                         'the rejected duplicate leaves the matrix untouched')

    def test_60_scan_switches_board_and_counts(self):
        # 扫码切换当前板；非法 SN 拦截；数量三件套随格联动
        order = self._order()
        s1, s2 = self._ready_samples(order, 'SN-MTX-D')
        inspection = order.x_fai_inspection_id
        inspection.x_fai_scan = s1.name
        inspection._onchange_x_fai_scan()
        self.assertEqual(inspection.x_fai_current_sn, s1,
                         'scanning a picked board switches the inspected board')
        self.assertFalse(inspection.x_fai_scan, 'the scan box clears itself')
        inspection.x_fai_scan = 'SN-NOT-IN-ROUND'
        with self.assertRaises(UserError):
            inspection._onchange_x_fai_scan()
        self.assertEqual((inspection.x_fai_ok_qty, inspection.x_fai_ng_qty), (2, 0),
                         'default-pass round counts 2 ok / 0 ng')
        self._cell(inspection, self.voltage_code, s2).write(
            {'measured_value': 25.0})
        self.assertEqual((inspection.x_fai_ok_qty, inspection.x_fai_ng_qty), (1, 1),
                         'one failing board counts 1 ng / 1 ok')
