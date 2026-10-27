from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRouteGraphEdit(TransactionCase):
    """制令单画布本地编辑（action_save_route_graph / _apply_graph）的回归：

    线上 bug：删除"冻结工序 → 未冻结工序"的连线保存后复活——保存逻辑曾
    无条件保留来自冻结行的旧边。连带：载荷不带的字段（手动工时、工作中心）
    曾被清零。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'WS-RT', 'code': 'WSRT'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LRT', 'code': 'LRT', 'workshop_id': cls.workshop.id,
        })
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True,
        ).create({'name': 'RT-EDIT', 'code': 'RTE', 'x_workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({'name': 'OP-PROG', 'code': 'PROG', 'x_station_type': 'programming'})
        cls.op_b = Operation.create({'name': 'OP-AOI', 'code': 'AOI2', 'x_station_type': 'inspection'})
        cls.op_c = Operation.create({'name': 'OP-FCT', 'code': 'FCT', 'x_station_type': 'final_test'})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_a.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_c.id, 'sequence': 20,
                        'time_cycle_manual': 55.0}),
            ],
            'x_daily_input_operation_id': cls.op_a.id,
            'x_daily_output_operation_id': cls.op_c.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-RT-EDIT',
        })
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[1].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        cls.product = cls.env['product.product'].create({
            'name': 'P-RT-EDIT', 'default_code': 'DWG-RT-EDIT',
            'x_board_side': 'single', 'uom_id': cls.env.ref('uom.product_uom_unit').id,
        })

    def _make_order(self):
        mo = self.env['mrp.production'].create({
            'product_id': self.product.id, 'product_qty': 10,
            'company_id': self.company.id,
        })
        return self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id, 'production_line_id': self.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': 10,
        })

    def _row(self, order, operation):
        return order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == operation)[:1]

    def _freeze(self, order, row):
        """One station scan at `row` → it carries execution records."""
        sn = self.env['sn.wsd.serial.identity'].sudo().get_or_create(
            'RT-EDIT-%s' % row.id, self.company, origin_type='manual')
        self.env['sn.wsd.serial.operation.history'].create({
            'serial_identity_id': sn.id, 'mes_order_id': order.id,
            'route_operation_id': row.id, 'result': 'in_progress',
            'in_date': fields.Datetime.now(),
        })

    def _node(self, row, seq, y):
        return {
            'uid': str(row.id), 'id': row.id,
            'operation_id': row.operation_id.id, 'name': row.name,
            'step_code': row.x_step_code, 'sequence': seq,
            'x_station_type': row.x_station_type,
            'x_allow_entry': row.x_allow_entry, 'x_allow_exit': row.x_allow_exit,
            'x': 30, 'y': y,
        }

    def _new_node(self, operation, seq, y):
        return {
            'uid': 'new_%s' % operation.code, 'id': None,
            'operation_id': operation.id, 'name': operation.name,
            'step_code': operation.code, 'sequence': seq,
            'x_station_type': operation.x_station_type,
            'time_cycle_manual': 42.0,
            'x_allow_entry': False, 'x_allow_exit': False,
            'x': 30, 'y': y,
        }

    def _edges(self, order):
        code = {r.id: r.operation_id.code for r in order.x_mes_route_id.operation_ids}
        return [(code[e['source']], code[e['target']])
                for e in order.x_mes_route_id.get_route_graph()['edges']]

    def test_removed_edge_from_frozen_source_stays_removed(self):
        """删除「已过站工序 → 未过站工序」的连线：保存后不得复活（线上 bug）。"""
        order = self._make_order()
        row_a, row_c = self._row(order, self.op_a), self._row(order, self.op_c)
        self._freeze(order, row_a)
        self.assertIn(('PROG', 'FCT'), self._edges(order))

        order.action_save_route_graph({
            'nodes': [
                self._node(row_a, 10, 30),
                self._new_node(self.op_b, 15, 120),
                self._node(row_c, 20, 210),
            ],
            'edges': [
                {'source': str(row_a.id), 'target': 'new_AOI2'},
                {'source': 'new_AOI2', 'target': str(row_c.id)},
            ],
        })

        edges = self._edges(order)
        self.assertNotIn(('PROG', 'FCT'), edges,
                         'deleted edge from a frozen source resurrected')
        self.assertIn(('PROG', 'AOI2'), edges)
        self.assertIn(('AOI2', 'FCT'), edges)

    def test_frozen_target_keeps_its_own_predecessors(self):
        """连线指向已过站工序：目标侧冻结，画布提交的进出边一概不改。"""
        order = self._make_order()
        row_a, row_c = self._row(order, self.op_a), self._row(order, self.op_c)
        self._freeze(order, row_c)

        order.action_save_route_graph({
            'nodes': [
                self._node(row_a, 10, 30),
                self._new_node(self.op_b, 15, 120),
                self._node(row_c, 20, 210),
            ],
            'edges': [
                {'source': str(row_a.id), 'target': 'new_AOI2'},
                {'source': 'new_AOI2', 'target': str(row_c.id)},
            ],
        })

        edges = self._edges(order)
        self.assertIn(('PROG', 'FCT'), edges,
                      'frozen target must keep its stored predecessors')
        self.assertNotIn(('AOI2', 'FCT'), edges,
                         'edges into a frozen target must not be added')

    def test_canvas_save_keeps_fields_missing_from_payload(self):
        """载荷不带的手动工时/工作中心：保留库里的值，不再被清零。"""
        order = self._make_order()
        row_a, row_c = self._row(order, self.op_a), self._row(order, self.op_c)
        self.assertEqual(row_c.time_cycle_manual, 55.0)

        order.action_save_route_graph({
            'nodes': [
                self._node(row_a, 10, 30),
                self._new_node(self.op_b, 15, 120),
                self._node(row_c, 20, 210),
            ],
            'edges': [
                {'source': str(row_a.id), 'target': 'new_AOI2'},
                {'source': 'new_AOI2', 'target': str(row_c.id)},
            ],
        })

        row_c = self._row(order, self.op_c)
        row_b = self._row(order, self.op_b)
        self.assertEqual(row_c.time_cycle_manual, 55.0,
                         'stored manual duration must survive a canvas save')
        self.assertEqual(row_b.time_cycle_manual, 42.0,
                         'new palette nodes carry their submitted duration')
