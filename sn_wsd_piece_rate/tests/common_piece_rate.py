from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class PieceRateTestCommon(TransactionCase):
    """piece-rate 测试公共夹具：车间/线/路线(2工序)/图号/制令单/员工/班组。
    路线：PRS-A(装配,投入) → PRS-B(终测,产出)；产品图号 DWG-PRS。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-PRS', 'code': 'WSPRS'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'PRS', 'code': 'PRS', 'workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({
            'name': 'PRS-A', 'code': 'PRSA', 'x_station_type': 'assembly'})
        cls.op_b = Operation.create({
            'name': 'PRS-B', 'code': 'PRSB', 'x_station_type': 'final_test'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-PRS', 'code': 'RTPRS',
                'x_workshop_id': cls.workshop.id,
                'state': 'confirmed',
                'x_production_side': 'single',
                'route_operation_ids': [
                    (0, 0, {'operation_id': cls.op_a.id, 'sequence': 10}),
                    (0, 0, {'operation_id': cls.op_b.id, 'sequence': 20}),
                ],
                'x_daily_input_operation_id': cls.op_a.id,
                'x_daily_output_operation_id': cls.op_b.id,
                'x_workorder_input_operation_id': cls.op_a.id,
            })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-PRS'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[1].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]

        Employee = cls.env['hr.employee']
        cls.emp_zhang = Employee.create({'name': 'PRS Zhang', 'barcode': 'PRSZ01'})
        cls.emp_li = Employee.create({'name': 'PRS Li', 'barcode': 'PRSZ02'})
        cls.emp_wang = Employee.create({'name': 'PRS Wang', 'barcode': 'PRSZ03'})
        cls.emp_zhao = Employee.create({'name': 'PRS Zhao', 'barcode': 'PRSZ04'})
        cls.team = cls.env['sn.mrp.team'].create({
            'name': 'PRS Team', 'code': 'PRS-T01',
            'workshop_id': cls.workshop.id,
            'production_line_id': cls.line.id,
            'member_ids': [
                (0, 0, {'employee_id': cls.emp_zhang.id,
                        'employee_code': 'PRSZ01',
                        'performance_ratio': 30.0, 'is_leader': True}),
                (0, 0, {'employee_id': cls.emp_li.id,
                        'employee_code': 'PRSZ02',
                        'performance_ratio': 30.0}),
                (0, 0, {'employee_id': cls.emp_wang.id,
                        'employee_code': 'PRSZ03',
                        'performance_ratio': 20.0}),
                (0, 0, {'employee_id': cls.emp_zhao.id,
                        'employee_code': 'PRSZ04',
                        'performance_ratio': 20.0}),
            ],
        })
        cls.order = cls._make_order_common()
        # 作废/关账是管理员动作，测试主用户挂管理员组；
        # 权限边界用例单独造非管理员用户（new user 无该组）。
        cls.env.user.group_ids = [(
            4, cls.env.ref('sn_wsd_piece_rate.group_piece_rate_manager').id)]

    @classmethod
    def _make_order_common(cls, qty=1000, mode='report'):
        if not hasattr(cls, '_prs_product'):
            cls._prs_product = cls.env['product.product'].create({
                'name': 'P-PRS', 'uom_id': cls.uom_unit.id,
                'default_code': 'DWG-PRS', 'x_board_side': 'single',
            })
        mo = cls.env['mrp.production'].create({
            'product_id': cls._prs_product.id, 'product_qty': qty,
            'company_id': cls.company.id,
        })
        return cls.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': cls.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': qty,
            'x_manage_mode': mode,
        })

    def _op_row(self, order, operation):
        return order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == operation)[:1]

    def _op_a_row(self, order):
        return self._op_row(order, self.op_a)

    def _make_report(self, order, operation, qty_ok, qty_ng=0.0, qty_scrap=0.0):
        return self.env['sn.wsd.mes.operation.report'].create({
            'mes_order_id': order.id,
            'route_operation_id': self._op_row(order, operation).id,
            'qty_ok': qty_ok,
            'qty_ng': qty_ng,
            'qty_scrap': qty_scrap,
        })

    def _settlement(self, qty=500.0, order=None):
        order = order or self.order
        return self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': order.id,
            'route_operation_id': self._op_a_row(order).id,
            'qty_ok': qty,
        })

    def _rate(self, price=0.3, operation=None):
        operation = operation or self.op_a
        existing = self.env['sn.wsd.piece.rate'].search([
            ('company_id', '=', self.env.company.id),
            ('product_id', '=', self.order.product_id.id),
            ('operation_id', '=', operation.id),
        ], limit=1)
        if existing:
            existing.price = price
            return existing
        return self.env['sn.wsd.piece.rate'].create({
            'product_id': self.order.product_id.id,
            'operation_id': operation.id,
            'price': price,
        })
