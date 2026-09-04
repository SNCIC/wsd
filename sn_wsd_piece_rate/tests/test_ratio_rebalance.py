from odoo import fields
from odoo.tests import Form, tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestProgressiveRatioRebalance(PieceRateTestCommon):
    """方案A 手改即锁定（2026-09-04）：改过的行（值≠基线）保持，
    其余行按基线权重分摊剩余；递进填写保留之前手改值；删除行重分；
    锁定行合计>100% 不自动改。"""

    def _draft_with_team(self):
        self._rate()
        report = self._make_report(self.order, self.op_a, 100.0)
        settlement = self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': self.order.id,
            'route_operation_id': self._op_a_row(self.order).id,
            'operation_report_id': report.id,
            'qty_ok': 100.0,
        })
        settlement._resolve_rate_price()
        settlement.team_id = self.team
        settlement.action_fill_from_team()  # 30/30/20/20，基线=同名值
        return settlement

    def test_progressive_lock(self):
        """改第2行→其余按 30:20:20 分摊；再改第1行→剩两行按 20:20 分摊。"""
        settlement = self._draft_with_team()
        with Form(settlement) as f:
            with f.participant_ids.edit(1) as line:  # 李 30 → 50
                line.performance_ratio = 50.0
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [21.4286, 50.0, 14.2857, 14.2857])  # 50 按 30:20:20 分摊
        with Form(settlement) as f:
            with f.participant_ids.edit(0) as line:  # 张 21.4286 → 20
                line.performance_ratio = 20.0
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [20.0, 50.0, 15.0, 15.0])  # 30 按 20:20 分摊，首改保留
        self.assertAlmostEqual(
            sum(settlement.participant_ids.mapped('performance_ratio')), 100.0,
            places=4)

    def test_equal_split_resets_baseline(self):
        """均分重置基线：之后手改一行，其余均分剩余。"""
        settlement = self._draft_with_team()
        settlement.action_equal_split()  # 25×4
        with Form(settlement) as f:
            with f.participant_ids.edit(0) as line:
                line.performance_ratio = 40.0
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [40.0, 20.0, 20.0, 20.0])

    def test_delete_row_rebalances(self):
        """删除一行：剩余 auto 行按基线权重归一到 100%。"""
        settlement = self._draft_with_team()
        with Form(settlement) as f:
            f.participant_ids.remove(index=3)  # 删 赵(20)
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [37.5, 37.5, 25.0])  # 100 按 30:30:20 分摊
        self.assertAlmostEqual(
            sum(settlement.participant_ids.mapped('performance_ratio')), 100.0,
            places=4)

    def test_over_100_leaves_auto_rows(self):
        """锁定行合计>100%：不自动改（负剩余），确认校验兜底。"""
        settlement = self._draft_with_team()
        with Form(settlement) as f:
            with f.participant_ids.edit(0) as line:
                line.performance_ratio = 60.0
        # 首改后：40 按 30:20:20 分摊 → 李 17.1429 / 王 11.4286 / 赵 11.4285
        with Form(settlement) as f:
            with f.participant_ids.edit(1) as line:
                line.performance_ratio = 60.0  # 锁定合计 120 > 100
        ratios = settlement.participant_ids.mapped('performance_ratio')
        self.assertEqual(ratios, [60.0, 60.0, 11.4286, 11.4285])  # auto 行未再动
