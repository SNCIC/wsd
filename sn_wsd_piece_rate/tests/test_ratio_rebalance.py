from odoo import fields
from odoo.tests import Form, tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestProgressiveRatioRebalance(PieceRateTestCommon):
    """日报工同款比例操作（2026-11-07 piece-ratio-to-settlement，替代
    2026-09-04 方案A）：显式锁定行+本次手输行保持，其余未锁定行**均分**
    剩余（尾差归末行）；手输封顶（100−其余固定行，截断+warning）；
    删除行重分；均分/带出全员解锁。"""

    def _draft_with_team(self):
        self._rate()
        # report-sourced settlements used to be read-only on this side;
        # rebalance runs on a plain draft (station / manual path).
        settlement = self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': self.order.id,
            'route_operation_id': self._op_a_row(self.order).id,
            'qty_ok': 100.0,
        })
        settlement._resolve_rate_price()
        settlement.team_id = self.team
        settlement.action_fill_from_team()  # 30/30/20/20，基线=同名值
        return settlement

    def test_progressive_lock(self):
        """改第2行→其余均分；再改第1行→前一次手改**不保留**（未锁定，
        与日报工一致）；锁定行穿越后续重摊保持。"""
        settlement = self._draft_with_team()
        with Form(settlement) as f:
            with f.participant_ids.edit(1) as line:  # 李 30 → 50
                line.performance_ratio = 50.0
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [16.6667, 50.0, 16.6667, 16.6666])  # 50 由 3 行均分
        with Form(settlement) as f:
            with f.participant_ids.edit(0) as line:  # 张 16.6667 → 20
                line.performance_ratio = 20.0
        # 李的 50 未锁定 → 随重摊被均分覆盖（80/3）
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [20.0, 26.6667, 26.6667, 26.6666])
        # 锁定李 26.6667 后再改张 → 李保持
        with Form(settlement) as f:
            with f.participant_ids.edit(1) as line:
                line.x_ratio_locked = True
            with f.participant_ids.edit(0) as line:  # 张 → 30
                line.performance_ratio = 30.0
        ratios = settlement.participant_ids.mapped('performance_ratio')
        self.assertEqual(ratios[0], 30.0)
        self.assertEqual(ratios[1], 26.6667)
        self.assertAlmostEqual(sum(ratios), 100.0, places=4)

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
        """删除一行：剩余未锁定行均分到 100%。"""
        settlement = self._draft_with_team()
        with Form(settlement) as f:
            f.participant_ids.remove(index=3)  # 删 赵(20)
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [33.3333, 33.3333, 33.3334])
        self.assertAlmostEqual(
            sum(settlement.participant_ids.mapped('performance_ratio')), 100.0,
            places=4)

    def test_typed_over_cap_truncates(self):
        """手输超过 100−其余固定行 → 截断到 cap（替代旧">100 不自动改"）：
        张锁定后改 60（其余 40/3），李再输 60 被截到 40，末两行归 0。"""
        settlement = self._draft_with_team()
        with Form(settlement) as f:
            with f.participant_ids.edit(0) as line:
                line.x_ratio_locked = True  # 张锁定
        with Form(settlement) as f:
            with f.participant_ids.edit(0) as line:
                line.performance_ratio = 60.0  # 其余均分 40/3
        ratios = settlement.participant_ids.mapped('performance_ratio')
        self.assertEqual(ratios, [60.0, 13.3333, 13.3333, 13.3334])
        with Form(settlement) as f:
            with f.participant_ids.edit(1) as line:
                line.performance_ratio = 60.0  # cap = 100 - 60 = 40
        ratios = settlement.participant_ids.mapped('performance_ratio')
        self.assertEqual(ratios, [60.0, 40.0, 0.0, 0.0])
