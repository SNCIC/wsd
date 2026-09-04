from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestLockClose(PieceRateTestCommon):
    """piece-rate 批次5：确认前置校验与全字段冻结、作废留痕与释放、
    月度关账（新增/确认/作废三处拦截 + 草稿警示 + 重开）。"""

    AUG = '2026-08-31'

    def _draft(self, qty=100.0, date=None):
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
        settlement.write({'participant_ids': [
            (0, 0, {'employee_id': self.emp_zhang.id, 'performance_ratio': 60.0}),
            (0, 0, {'employee_id': self.emp_li.id, 'performance_ratio': 40.0}),
        ]})
        return settlement

    def test_confirm_validations(self):
        """确认前置：无参与人 / 比例≠100 / 数量≤0 / 未解析单价 均拒绝。"""
        settlement = self._draft()
        settlement.participant_ids = [(5, 0)]
        with self.assertRaises(ValidationError):
            settlement.action_confirm()
        settlement = self._draft()
        settlement.participant_ids[0].performance_ratio = 50.0
        with self.assertRaises(ValidationError):
            settlement.action_confirm()
        settlement = self._draft()
        settlement.qty_ok = 0.0
        with self.assertRaises(ValidationError):
            settlement.action_confirm()
        settlement = self._draft()
        settlement.price = 0.0
        with self.assertRaises(ValidationError):
            settlement.action_confirm()

    def test_confirm_freezes_fields(self):
        """确认后全字段冻结：改人/改量均拒绝；比例约束兜底坏数据。"""
        settlement = self._draft()
        settlement.action_confirm()
        self.assertEqual(settlement.state, 'confirmed')
        with self.assertRaises(UserError):
            settlement.write({'qty_ok': 50.0})
        with self.assertRaises(UserError):
            settlement.write({'participant_ids': [
                (5, 0),
                (0, 0, {'employee_id': self.emp_wang.id, 'performance_ratio': 100.0}),
            ]})

    def test_void_audited_and_releases(self):
        """作废留痕（人/时间）且释放报工行，可二次结算。"""
        self._rate()
        report = self._make_report(self.order, self.op_a, 300.0)
        settlement = self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': self.order.id,
            'route_operation_id': self._op_a_row(self.order).id,
            'operation_report_id': report.id,
            'qty_ok': 300.0,
            'date': fields.Date.to_date(self.AUG),
        })
        settlement._resolve_rate_price()
        settlement.write({'participant_ids': [
            (0, 0, {'employee_id': self.emp_zhang.id, 'performance_ratio': 100.0}),
        ]})
        settlement.action_confirm()
        settlement.action_void()
        self.assertEqual(settlement.state, 'void')
        self.assertTrue(settlement.voided_by)
        self.assertTrue(settlement.voided_at)
        self.assertFalse(report.x_piece_settled)
        reborn = self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': self.order.id,
            'route_operation_id': self._op_a_row(self.order).id,
            'operation_report_id': report.id,
            'qty_ok': 300.0,
            'date': fields.Date.to_date(self.AUG),
        })
        self.assertTrue(reborn.operation_report_id)

    def test_void_needs_manager(self):
        """非管理员作废被拒。"""
        settlement = self._draft()
        settlement.action_confirm()
        clerk = self.env['res.users'].create({
            'name': 'PRS Clerk',
            'login': 'prs_clerk',
            'email': 'prs.cler@example.com',
            'group_ids': [(
                6, 0, [self.env.ref('sn_wsd_piece_rate.group_piece_rate_user').id])],
        })
        with self.assertRaises(UserError):
            settlement.with_user(clerk).action_void()

    def test_month_close_full_flow(self):
        """关账月：新增/确认/作废三处拦截；重开后全部放行（月初重算流程）。"""
        settlement = self._draft(date=fields.Date.to_date(self.AUG))
        wizard = self.env['sn.wsd.piece.close.wizard'].create({
            'period': '2026-08',
        })
        self.assertEqual(wizard.draft_count, 1)
        with self.assertRaises(UserError):
            wizard.action_close()  # 有草稿必须先确认勾选
        wizard.acknowledge_drafts = True
        wizard.action_close()
        self.assertTrue(settlement.month_closed)
        # 新增被拦
        with self.assertRaises(UserError):
            self._settlement(50.0, order=self.order).date = fields.Date.to_date(self.AUG)
        # 确认被拦
        with self.assertRaises(UserError):
            settlement.action_confirm()
        # 作废被拦（先把草稿绕过关账确认掉再验作废：直接建一张8月已确认单验证作废拦截）
        reopen = self.env['sn.wsd.piece.close.wizard'].create({'period': '2026-08'})
        reopen.action_reopen()
        settlement.action_confirm()
        close2 = self.env['sn.wsd.piece.close.wizard'].create({'period': '2026-08'})
        close2.acknowledge_drafts = True
        close2.action_close()
        with self.assertRaises(UserError):
            settlement.action_void()
        # 重开 → 作废放行
        self.env['sn.wsd.piece.close.wizard'].create(
            {'period': '2026-08'}).action_reopen()
        settlement.action_void()
        self.assertEqual(settlement.state, 'void')

    def test_period_format_guard(self):
        wizard = self.env['sn.wsd.piece.close.wizard'].create({'period': '2026-13'})
        with self.assertRaises(ValidationError):
            wizard.action_close()
