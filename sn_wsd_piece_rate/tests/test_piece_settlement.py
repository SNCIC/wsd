from odoo.exceptions import UserError
from odoo.tests import tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestPieceSettlement(PieceRateTestCommon):
    """piece-rate 批次2：结算单与分摊——快照单价、金额与分摊计算（尾差不补）、
    班组归一化带出、均分、非成员默认均分、缺单价硬拦。
    比例合计=100 的强制在确认动作（批次5）落地，草稿自由编辑。"""

    def test_amount_and_allocation(self):
        """500台×0.30=150.00；37.5/37.5/25 → 56.25/56.25/37.50。"""
        self._rate(0.3)
        settlement = self._settlement(500.0)
        settlement._resolve_rate_price()
        self.assertAlmostEqual(settlement.price, 0.3)
        self.assertAlmostEqual(settlement.amount, 150.0, places=2)
        settlement.write({'participant_ids': [
            (0, 0, {'employee_id': self.emp_zhang.id, 'performance_ratio': 37.5}),
            (0, 0, {'employee_id': self.emp_li.id, 'performance_ratio': 37.5}),
            (0, 0, {'employee_id': self.emp_wang.id, 'performance_ratio': 25.0}),
        ]})
        self.assertEqual(
            settlement.participant_ids.mapped('amount'), [56.25, 56.25, 37.5])
        self.assertAlmostEqual(settlement.allocated_total, 150.0, places=2)

    def test_tail_rounding_dropped(self):
        """10.00 元 3 人均分 → 各 3.33，合计 9.99，尾差 0.01 不补。"""
        self._rate(0.1)
        settlement = self._settlement(100.0)
        settlement._resolve_rate_price()
        self.assertAlmostEqual(settlement.amount, 10.0, places=2)
        settlement.write({'participant_ids': [
            (0, 0, {'employee_id': self.emp_zhang.id}),
            (0, 0, {'employee_id': self.emp_li.id}),
            (0, 0, {'employee_id': self.emp_wang.id}),
        ]})
        settlement.action_equal_split()
        ratios = settlement.participant_ids.mapped('performance_ratio')
        self.assertAlmostEqual(sum(ratios), 100.0, places=4)
        self.assertEqual(
            settlement.participant_ids.mapped('amount'), [3.33, 3.33, 3.33])
        self.assertAlmostEqual(settlement.allocated_total, 9.99, places=2)

    def test_fill_from_team_all_members(self):
        """未预选参与人 → 带出全员，比例即班组原比例（合计已 100）。"""
        self._rate()
        settlement = self._settlement()
        settlement.team_id = self.team
        settlement.action_fill_from_team()
        self.assertEqual(
            settlement.participant_ids.mapped('employee_id'),
            self.team.member_ids.mapped('employee_id'))
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [30.0, 30.0, 20.0, 20.0])

    def test_fill_from_team_subset_normalized(self):
        """当次参与人仅 张/李/王 → 30/30/20 归一化为 37.5/37.5/25.0。"""
        self._rate()
        settlement = self._settlement()
        settlement.write({'participant_ids': [
            (0, 0, {'employee_id': self.emp_zhang.id}),
            (0, 0, {'employee_id': self.emp_li.id}),
            (0, 0, {'employee_id': self.emp_wang.id}),
        ]})
        settlement.team_id = self.team
        settlement.action_fill_from_team()
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [37.5, 37.5, 25.0])

    def test_non_member_equal_default(self):
        """非班组成员加入 → 按当前人数均分默认（1 人在册 + 新人 = 各 50）。"""
        self._rate()
        settlement = self._settlement()
        settlement.write({'participant_ids': [
            (0, 0, {'employee_id': self.emp_zhang.id, 'performance_ratio': 100.0}),
        ]})
        Participant = self.env['sn.wsd.piece.settlement.participant']
        new_line = Participant.new({'settlement_id': settlement.id})
        new_line.employee_id = self.emp_zhao
        new_line._onchange_employee_id_default_ratio()
        self.assertAlmostEqual(new_line.performance_ratio, 50.0, places=4)

    def test_missing_rate_blocks(self):
        """产品×工序未配单价 → 解析被硬拦。"""
        settlement = self._settlement()
        self.env['sn.wsd.piece.rate'].create({
            'product_id': self.order.product_id.id,
            'operation_id': self.op_b.id,
            'price': 0.2,
        })
        with self.assertRaises(UserError):
            settlement._resolve_rate_price()

    def test_price_snapshot_immutable(self):
        """结算后改单价表，已生成单据快照与金额不变。"""
        rate = self._rate(0.3)
        settlement = self._settlement(500.0)
        settlement._resolve_rate_price()
        rate.price = 0.35
        self.assertAlmostEqual(settlement.price, 0.3)
        self.assertAlmostEqual(settlement.amount, 150.0, places=2)
        other = self._settlement(100.0)
        other._resolve_rate_price()
        self.assertAlmostEqual(other.price, 0.35)


@tagged('post_install', '-at_install')
class TestSettlementRatioRebalance(PieceRateTestCommon):
    """结算单比例操作=日报工同款（2026-11-07 piece-ratio-to-settlement）：
    显式锁定行+本次手输行固定、其余未锁定行均分剩余（尾差归末行）、
    手输封顶（100−其余固定行，截断+warning）、均分/带出全员解锁。"""

    def _crew(self, ratios=(40.0, 30.0, 30.0)):
        settlement = self._settlement(100.0)
        settlement.write({'participant_ids': [
            (0, 0, {'employee_id': self.emp_zhang.id,
                    'performance_ratio': ratios[0],
                    'x_ratio_baseline': ratios[0]}),
            (0, 0, {'employee_id': self.emp_li.id,
                    'performance_ratio': ratios[1],
                    'x_ratio_baseline': ratios[1]}),
            (0, 0, {'employee_id': self.emp_wang.id,
                    'performance_ratio': ratios[2],
                    'x_ratio_baseline': ratios[2]}),
        ]})
        return settlement

    def _by_employee(self, settlement):
        return {p.employee_id.name: p for p in settlement.participant_ids}

    def test_manual_keeps_others_split_evenly(self):
        """手输 50：该行固定，其余未锁定行均分剩余（非按基线权重）。"""
        settlement = self._crew()
        crew = self._by_employee(settlement)
        crew['PRS Zhang'].performance_ratio = 50.0  # typed over baseline 40
        settlement._onchange_participant_ids_rebalance()
        crew = self._by_employee(settlement)
        self.assertEqual(crew['PRS Zhang'].performance_ratio, 50.0)
        self.assertEqual(crew['PRS Li'].performance_ratio, 25.0)
        self.assertEqual(crew['PRS Wang'].performance_ratio, 25.0)

    def test_lock_keeps_through_manual_edit(self):
        """锁定行穿越重摊保持不变。"""
        settlement = self._crew()
        crew = self._by_employee(settlement)
        crew['PRS Li'].x_ratio_locked = True  # 30 locked
        crew['PRS Zhang'].performance_ratio = 50.0
        settlement._onchange_participant_ids_rebalance()
        crew = self._by_employee(settlement)
        self.assertEqual(crew['PRS Li'].performance_ratio, 30.0)
        self.assertEqual(crew['PRS Zhang'].performance_ratio, 50.0)
        self.assertEqual(crew['PRS Wang'].performance_ratio, 20.0)

    def test_typed_value_capped_with_warning(self):
        """锁定 60 后手输 50 → 封顶到 40 并返回 warning，末行 0。"""
        settlement = self._crew()
        crew = self._by_employee(settlement)
        crew['PRS Zhang'].x_ratio_locked = True
        crew['PRS Zhang'].performance_ratio = 60.0
        settlement._onchange_participant_ids_rebalance()  # commit the lock pass
        crew = self._by_employee(settlement)
        crew['PRS Li'].performance_ratio = 50.0  # cap = 100 - 60 = 40
        warning = settlement._onchange_participant_ids_rebalance()
        crew = self._by_employee(settlement)
        self.assertEqual(crew['PRS Zhang'].performance_ratio, 60.0)
        self.assertEqual(crew['PRS Li'].performance_ratio, 40.0)
        self.assertEqual(crew['PRS Wang'].performance_ratio, 0.0)
        self.assertTrue(warning and warning.get('warning'))

    def test_equal_split_releases_locks(self):
        """均分：全员 1/N 且全部解锁。"""
        settlement = self._crew()
        crew = self._by_employee(settlement)
        crew['PRS Zhang'].x_ratio_locked = True
        settlement.action_equal_split()
        self.assertFalse(settlement.participant_ids.filtered('x_ratio_locked'))
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [33.3333, 33.3333, 33.3334])

    def test_fill_from_team_releases_locks(self):
        """从班组带出：既有成员按成员权重归一化（37.5/37.5/25）+全部解锁。"""
        self._rate(0.3)
        settlement = self._crew()
        settlement.team_id = self.team
        crew = self._by_employee(settlement)
        crew['PRS Zhang'].x_ratio_locked = True
        settlement.action_fill_from_team()
        self.assertFalse(settlement.participant_ids.filtered('x_ratio_locked'))
        self.assertEqual(
            settlement.participant_ids.mapped('employee_id.name'),
            ['PRS Zhang', 'PRS Li', 'PRS Wang'])
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [37.5, 37.5, 25.0])
