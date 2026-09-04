from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestReportSource(PieceRateTestCommon):
    """piece-rate 批次3：报工模式数量来源——报工行 1:1 占用（草稿即占用、
    作废释放）、批量生成向导。"""

    def test_report_settled_once(self):
        """一笔报工行只能被一张未作废计件单引用；草稿即占用。"""
        self._rate()
        report = self._make_report(self.order, self.op_a, 400.0)
        self.assertFalse(report.x_piece_settled)
        settlement = self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': self.order.id,
            'route_operation_id': self._op_a_row(self.order).id,
            'operation_report_id': report.id,
            'qty_ok': report.qty_ok,
        })
        self.assertTrue(report.x_piece_settled)
        # search 路径（'=' 会被 ORM 规范成 'in'，回归 2026-09-04 浏览器验证发现）
        Report = self.env['sn.wsd.mes.operation.report']
        settled = Report.search([('x_piece_settled', '=', True)])
        self.assertIn(report, settled)
        self.assertNotIn(
            self._make_report(self.order, self.op_a, 1.0), settled)
        self.assertNotIn(report, Report.search([('x_piece_settled', '=', False)]))
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.piece.settlement'].create({
                'mes_order_id': self.order.id,
                'route_operation_id': self._op_a_row(self.order).id,
                'operation_report_id': report.id,
                'qty_ok': report.qty_ok,
            })
        # 同单作废后可再次结算（占用释放）
        settlement.state = 'void'
        self.assertFalse(report.x_piece_settled)
        reborn = self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': self.order.id,
            'route_operation_id': self._op_a_row(self.order).id,
            'operation_report_id': report.id,
            'qty_ok': report.qty_ok,
        })
        self.assertTrue(reborn.operation_report_id)

    def test_generate_wizard(self):
        """向导筛选未结算报工行批量生成草稿：带出数量/业务日期/快照/默认参与人。"""
        self._rate()
        reports = [
            self._make_report(self.order, self.op_a, 100.0),
            self._make_report(self.order, self.op_a, 400.0),
            self._make_report(self.order, self.op_b, 200.0),
        ]
        wizard = self.env['sn.wsd.piece.settlement.generate.wizard'].create({
            'mes_order_id': self.order.id,
            'report_ids': [(6, 0, reports[0].ids + reports[1].ids)],
        })
        action = wizard.action_generate()
        domain_ids = [d[2] for d in action['domain'] if d[0] == 'id'][0]
        settlements = self.env['sn.wsd.piece.settlement'].browse(domain_ids)
        self.assertEqual(len(settlements), 2)
        by_qty = {s.qty_ok: s for s in settlements}
        self.assertAlmostEqual(by_qty[100.0].price, 0.3)
        self.assertAlmostEqual(by_qty[100.0].amount, 30.0, places=2)
        self.assertAlmostEqual(by_qty[400.0].amount, 120.0, places=2)
        # 单班组默认参与人已带出（归一化=原比例）
        for settlement in settlements:
            self.assertEqual(
                settlement.participant_ids.mapped('performance_ratio'),
                [30.0, 30.0, 20.0, 20.0])
            self.assertEqual(settlement.state, 'draft')
        # 已占用的两笔报工行不再出现在未结算列表
        wizard2 = self.env['sn.wsd.piece.settlement.generate.wizard'].create({
            'mes_order_id': self.order.id,
        })
        wizard2._onchange_filters_load_reports()
        self.assertEqual(wizard2.report_ids.ids, reports[2].ids)

    def test_source_consistency(self):
        """确认前源校验：报工模式必须有报工行、数量必须一致、
        非报工模式不得挂报工行。"""
        self._rate()
        settlement = self._settlement(500.0)  # 报工模式单，无报工引用
        with self.assertRaises(ValidationError):
            settlement._validate_source()
        report = self._make_report(self.order, self.op_a, 500.0)
        settlement.operation_report_id = report
        settlement._validate_source()
        settlement.qty_ok = 499.0
        with self.assertRaises(ValidationError):
            settlement._validate_source()
        settlement.qty_ok = 500.0
        settlement._validate_source()
        # 过站模式挂报工行 → 拒绝（用另一笔未占用报工行，避免撞 1:1 占用）
        station_order = self._make_order_common(mode='station')
        station_settlement = self._settlement(10.0, order=station_order)
        station_settlement.operation_report_id = self._make_report(
            self.order, self.op_a, 1.0)
        with self.assertRaises(ValidationError):
            station_settlement._validate_source()
