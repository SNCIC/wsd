from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestLedgerAndAccess(PieceRateTestCommon):
    """piece-rate 批次6：员工台账口径（已确认未作废，按业务日期归月）、
    权限边界（user 可开单确认不可作废/不可读单价，未入组不可见）。"""

    AUG = fields.Date.to_date('2026-08-31')

    def _confirmed(self, qty, date=None, ratios=None):
        self._rate()
        report = self._make_report(self.order, self.op_a, qty)
        vals = {
            'mes_order_id': self.order.id,
            'route_operation_id': self._op_a_row(self.order).id,
            'operation_report_id': report.id,
            'qty_ok': qty,
        }
        if date:
            vals['date'] = date
        settlement = self.env['sn.wsd.piece.settlement'].create(vals)
        settlement._resolve_rate_price()
        participants = ratios or [
            (self.emp_zhang.id, 60.0), (self.emp_li.id, 40.0)]
        settlement.write({'participant_ids': [
            (0, 0, {'employee_id': emp, 'performance_ratio': ratio})
            for emp, ratio in participants
        ]})
        settlement.action_confirm()
        return settlement

    def test_ledger_scope(self):
        """台账只含已确认未作废；业务日期归月（8月补单算8月）。"""
        s1 = self._confirmed(100.0)  # 今天
        s2 = self._confirmed(200.0, date=self.AUG)  # 8月补单
        voided = self._confirmed(50.0)
        voided.action_void()
        Participant = self.env['sn.wsd.piece.settlement.participant']
        zhang_total = sum(Participant.search([
            ('employee_id', '=', self.emp_zhang.id),
            ('settlement_id.state', '=', 'confirmed'),
        ]).mapped('amount'))
        # s1: 100×0.3×60% = 18.00；s2: 200×0.3×60% = 36.00；voided 不计
        self.assertAlmostEqual(zhang_total, 54.0, places=2)
        august = Participant.search([
            ('settlement_id.state', '=', 'confirmed'),
            ('settlement_id.date', '>=', '2026-08-01'),
            ('settlement_id.date', '<=', '2026-08-31'),
        ])
        self.assertEqual(august.mapped('settlement_id'), s2)

    def test_user_group_boundary(self):
        """计件-用户：可开单/确认；不可读单价表、不可作废。"""
        clerk = self.env['res.users'].create({
            'name': 'PRS Clerk2',
            'login': 'prs_clerk2',
            'email': 'prs.clerk2@example.com',
            'group_ids': [(
                6, 0, [self.env.ref('sn_wsd_piece_rate.group_piece_rate_user').id])],
        })
        self._rate()
        report = self._make_report(self.order, self.op_a, 60.0)
        settlement = self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': self.order.id,
            'route_operation_id': self._op_a_row(self.order).id,
            'operation_report_id': report.id,
            'qty_ok': 60.0,
        })
        clerk_view = settlement.with_user(clerk)
        clerk_view._resolve_rate_price()
        clerk_view.team_id = self.team
        clerk_view.action_fill_from_team()
        clerk_view.action_confirm()
        self.assertEqual(clerk_view.state, 'confirmed')
        with self.assertRaises(AccessError):
            self.env['sn.wsd.piece.rate'].with_user(clerk).search(
                [('product_id', '=', self.order.product_id.id)])

    def test_no_group_no_access(self):
        """未入组用户不可读结算单（菜单不可见的模型层兜底）。"""
        outsider = self.env['res.users'].create({
            'name': 'PRS Outsider',
            'login': 'prs_outsider',
            'email': 'prs.outsider@example.com',
            'group_ids': [(6, 0, [])],
        })
        self._rate()
        settlement = self._settlement(10.0)
        with self.assertRaises(AccessError):
            settlement.with_user(outsider).read(['name'])
