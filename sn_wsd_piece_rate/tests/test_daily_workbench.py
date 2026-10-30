from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestDailyWorkbench(PieceRateTestCommon):
    """report-daily-workbench：日报工提交（分配前移）、自动计件草稿、
    分配修改窗口与整批事务回滚。"""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _order_with_pick(self, qty=1000):
        order = self._make_order_common(qty=qty, mode='report')
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(self.env, order)
        return order

    def _wizard_line(self, wizard, order, operation, qty_ok=0.0,
                     qty_ng=0.0, qty_scrap=0.0, scrap_reason=None,
                     team=None, allocation=()):
        line_model = self.env['sn.wsd.piece.report.wizard.line']
        return line_model.create({
            'wizard_id': wizard.id,
            'mes_order_id': order.id,
            'route_operation_id': self._op_row(order, operation).id,
            'qty_ok': qty_ok,
            'qty_ng': qty_ng,
            'qty_scrap': qty_scrap,
            'scrap_reason_id': scrap_reason.id if scrap_reason else False,
            'team_id': team.id if team else False,
            'participant_ids': [
                (0, 0, {'employee_id': employee.id,
                        'performance_ratio': ratio})
                for employee, ratio in allocation],
        })

    def _wizard(self):
        return self.env['sn.wsd.piece.settlement.generate.wizard'].create({})

    def _reports(self, order):
        return self.env['sn.wsd.mes.operation.report'].search(
            [('mes_order_id', '=', order.id)])

    # ------------------------------------------------------------------
    # submit entry: allocation mandatory when a rate exists
    # ------------------------------------------------------------------

    def test_submit_without_participants_blocked_when_rated(self):
        """有单价未分配 → 整批拦截，且无任何报工行落库。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0)
        with self.assertRaises(ValidationError) as ctx:
            wizard.action_submit_reports()
        self.assertIn('select the participants', str(ctx.exception))
        self.assertFalse(self._reports(order))

    def test_submit_ratio_total_must_be_100(self):
        """有单价且比例合计 ≠ 100% → 拦截。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0, allocation=(
            (self.emp_zhang, 45.0), (self.emp_li, 45.0)))
        with self.assertRaises(ValidationError) as ctx:
            wizard.action_submit_reports()
        self.assertIn('must be 100%', str(ctx.exception))
        self.assertFalse(self._reports(order))

    def test_submit_without_rate_passes_without_allocation(self):
        """无单价不强制：只录数量成功，行标待结算、不生成草稿。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0)
        wizard.action_submit_reports()
        report = self._reports(order)
        self.assertEqual(len(report), 1)
        self.assertFalse(report.participant_ids)
        self.assertFalse(report.piece_settlement_ids)
        self.assertFalse(report.x_piece_settled)
        self.assertEqual(report.x_piece_settled_label, 'Unsettled')

    def test_submit_pure_ng_line_skips_allocation_check(self):
        """qty_ok=0 的纯 NG 行不强制分配（未配单价亦同）。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ng=5.0)
        wizard.action_submit_reports()
        self.assertEqual(self._reports(order).qty_ng, 5.0)

    def test_submit_scrap_requires_reason(self):
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_scrap=1.0)
        with self.assertRaises(ValidationError) as ctx:
            wizard.action_submit_reports()
        self.assertIn('scrap reason', str(ctx.exception))

    # ------------------------------------------------------------------
    # one transaction: any rejected line rolls the whole batch back
    # ------------------------------------------------------------------

    def test_submit_batch_rolls_back_on_rejected_line(self):
        """3 行中 1 行超计划余量 → 整批失败，指明行与原因，零落库。"""
        self._rate()
        order = self._order_with_pick(qty=10)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=4.0, allocation=(
            (self.emp_zhang, 100.0),))
        self._wizard_line(wizard, order, self.op_a, qty_ok=3.0, allocation=(
            (self.emp_zhang, 100.0),))
        # planned 10, first two lines already consume 7 -> 5 exceeds the rest
        self._wizard_line(wizard, order, self.op_a, qty_ok=5.0, allocation=(
            (self.emp_zhang, 100.0),))
        with self.assertRaises(ValidationError) as ctx:
            with self.env.cr.savepoint():
                wizard.action_submit_reports()
        self.assertIn('exceeds the plan remainder', str(ctx.exception))
        self.assertIn('Line 3', str(ctx.exception))
        # whole batch rolled back: no report row and no state change
        self.assertFalse(self._reports(order))
        self.assertEqual(order.state, 'released')
        self.assertEqual(
            order.x_route_operation_ids.mapped('x_reported_ok_qty'),
            [0.0, 0.0])

    def test_submit_multiple_lines_all_pass(self):
        """一次提交多行：各工序落行、带各自分配、计数器随报更新。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=60.0, allocation=(
            (self.emp_zhang, 45.0), (self.emp_li, 55.0)))
        self._wizard_line(wizard, order, self.op_b, qty_ok=40.0, allocation=(
            (self.emp_wang, 100.0),))
        result = wizard.action_submit_reports()
        self.assertEqual(result['type'], 'ir.actions.client')
        reports = self._reports(order)
        self.assertEqual(len(reports), 2)
        op_a_row = self._op_a_row(order)
        self.assertEqual(op_a_row.x_reported_ok_qty, 60.0)
        self.assertEqual(
            self._op_row(order, self.op_b).x_reported_ok_qty, 40.0)
        report_a = reports.filtered(
            lambda r: r.route_operation_id == op_a_row)
        self.assertEqual(
            report_a.participant_ids.mapped('performance_ratio'), [45.0, 55.0])

    def test_submit_skips_untouched_preloaded_lines(self):
        """预载参照行（三数量全 0）不参与提交，不阻塞其他行。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a)
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0, allocation=(
            (self.emp_zhang, 100.0),))
        self._wizard_line(wizard, order, self.op_b)
        wizard.action_submit_reports()
        reports = self._reports(order)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports.qty_ok, 10.0)
        self.assertEqual(
            self._op_row(order, self.op_b).x_reported_ok_qty, 0.0)

    def test_submit_all_lines_zero_blocked(self):
        """全部行都是 0 → 明确提示至少录一个数量，零落库。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a)
        with self.assertRaises(UserError) as ctx:
            wizard.action_submit_reports()
        self.assertIn('at least one positive quantity', str(ctx.exception))
        self.assertFalse(self._reports(order))

    # ------------------------------------------------------------------
    # auto draft: copy allocation, snapshot price, business date
    # ------------------------------------------------------------------

    def test_submit_auto_draft_copies_allocation(self):
        """提交自动建草稿：qty_ok/单价快照/业务日期=报工时间/参与人原样复制。"""
        self._rate(price=0.3)
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(
            wizard, order, self.op_a, qty_ok=100.0, team=self.team,
            allocation=((self.emp_zhang, 45.0), (self.emp_li, 55.0)))
        wizard.action_submit_reports()
        report = self._reports(order)
        self.assertEqual(len(report), 1)
        self.assertEqual(report.team_id, self.team)
        settlement = report.piece_settlement_ids
        self.assertEqual(len(settlement), 1)
        self.assertEqual(settlement.state, 'draft')
        self.assertEqual(settlement.qty_ok, 100.0)
        self.assertAlmostEqual(settlement.price, 0.3)
        self.assertAlmostEqual(settlement.amount, 30.0)
        self.assertEqual(settlement.date, report.reported_at.date())
        self.assertEqual(settlement.team_id, self.team)
        copied = settlement.participant_ids
        self.assertEqual(copied.mapped('employee_id'),
                         report.participant_ids.mapped('employee_id'))
        self.assertEqual(copied.mapped('performance_ratio'), [45.0, 55.0])
        self.assertEqual(copied.mapped('amount'), [13.5, 16.5])
        self.assertTrue(report.x_piece_settled)

    def test_submit_skips_auto_draft_when_month_closed(self):
        """业务月已关 → 报工成功、不建草稿、不报关账错误。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        self.env['sn.wsd.piece.close.log'].create({
            'company_id': self.env.company.id,
            'period': self.env['sn.wsd.piece.close.log']._period_of(
                fields.Date.today()),
            'action': 'close',
        })
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0, allocation=(
            (self.emp_zhang, 100.0),))
        wizard.action_submit_reports()  # no error raised
        report = self._reports(order)
        self.assertEqual(len(report), 1)
        self.assertFalse(report.piece_settlement_ids)
        self.assertFalse(report.x_piece_settled)

    def test_terminal_call_without_allocation_stays_backlog(self):
        """终端式直调（不传分配）向后兼容：返回新报工行、不建草稿、行待分配。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        report = order.report_operation_qty(
            self._op_a_row(order), 5.0)
        self.assertEqual(len(report), 1)
        self.assertEqual(report.qty_ok, 5.0)
        self.assertFalse(report.participant_ids)
        self.assertFalse(report.piece_settlement_ids)
        # the row surfaces on the To Allocate tab
        wizard = self._wizard()
        wizard._onchange_filters_load_reports()
        self.assertIn(report, wizard.report_ids)

    # ------------------------------------------------------------------
    # edit window: frozen after confirm, synced while draft
    # ------------------------------------------------------------------

    def test_confirmed_settlement_freezes_allocation(self):
        """草稿确认后分配冻结：改/删/增参与人均拒绝。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0, allocation=(
            (self.emp_zhang, 45.0), (self.emp_li, 55.0)))
        wizard.action_submit_reports()
        report = self._reports(order)
        settlement = report.piece_settlement_ids
        settlement.action_confirm()
        with self.assertRaises(UserError) as ctx:
            report.participant_ids[0].performance_ratio = 50.0
        self.assertIn('frozen', str(ctx.exception))
        with self.assertRaises(UserError):
            report.participant_ids.unlink()
        with self.assertRaises(UserError):
            self.env['sn.wsd.mes.operation.report.participant'].create({
                'report_id': report.id,
                'employee_id': self.emp_wang.id,
                'performance_ratio': 10.0,
            })

    def test_draft_settlement_syncs_allocation(self):
        """未确认前改报工分配 → 草稿参与人同步、金额重算。"""
        self._rate(price=0.3)
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=100.0, allocation=(
            (self.emp_zhang, 45.0), (self.emp_li, 55.0)))
        wizard.action_submit_reports()
        report = self._reports(order)
        settlement = report.piece_settlement_ids
        self.assertEqual(
            settlement.participant_ids.mapped('amount'), [13.5, 16.5])
        report.participant_ids[0].performance_ratio = 40.0
        self.assertEqual(
            settlement.participant_ids.mapped('performance_ratio'),
            [40.0, 55.0])
        self.assertEqual(
            settlement.participant_ids.mapped('amount'), [12.0, 16.5])

    def test_void_then_regenerate_copies_latest_allocation(self):
        """作废释放后补生成：新草稿复制最新分配，作废单留痕不变。"""
        self._rate(price=0.3)
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=100.0, allocation=(
            (self.emp_zhang, 45.0), (self.emp_li, 55.0)))
        wizard.action_submit_reports()
        report = self._reports(order)
        first = report.piece_settlement_ids
        first.action_void()
        self.assertFalse(report.x_piece_settled)
        # the allocation was corrected after the void
        report.participant_ids[0].performance_ratio = 40.0
        report.participant_ids[1].performance_ratio = 60.0
        wizard2 = self._wizard()
        wizard2.report_ids = [(6, 0, report.ids)]
        wizard2.action_generate()
        reborn = report.piece_settlement_ids.filtered(
            lambda s: s.state != 'void')
        self.assertEqual(len(reborn), 1)
        self.assertEqual(
            reborn.participant_ids.mapped('performance_ratio'), [40.0, 60.0])
        self.assertEqual(first.state, 'void')

    # ------------------------------------------------------------------
    # wizard To Report tab: line load + participant prefill
    # ------------------------------------------------------------------

    def test_wizard_loads_active_orders_with_prefill(self):
        """待报工页签 onchange：活跃报工单的工序行带出，参与人预填
        = 该工序上次报工的分配；无历史再班组绩效比归一化。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        # first batch reported through the wizard with zhang 45 / li 55
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0, allocation=(
            (self.emp_zhang, 45.0), (self.emp_li, 55.0)))
        wizard.action_submit_reports()
        # a fresh wizard brings the lines of the (still active) order
        wizard2 = self._wizard()
        wizard2.mes_order_id = order.id
        wizard2._onchange_load_report_lines()
        lines = wizard2.report_line_ids
        self.assertEqual(len(lines), 2)  # one row per route operation
        line_a = lines.filtered(
            lambda l: l.route_operation_id == self._op_a_row(order))
        line_b = lines - line_a
        self.assertEqual(line_a.qty_ok, 0.0)
        self.assertEqual(
            line_a.participant_ids.mapped('performance_ratio'), [45.0, 55.0])
        # op_b has no report history: the unique active team of the line is
        # used, member ratios normalized (30/30/20/20 already totals 100)
        self.assertEqual(
            line_b.participant_ids.mapped('performance_ratio'),
            [30.0, 30.0, 20.0, 20.0])
        # op_b is sequence-locked until op_a flows more quantity? after the
        # first submit 10 units are upstream -> not locked; nothing reported
        # at op_b yet -> remainder = plan - 0
        self.assertEqual(line_b.reported_qty, 0.0)
        self.assertFalse(line_b.sequence_locked)

    def test_wizard_line_progress_counters(self):
        """行展示 计划/已报/可报额度 与顺序锁状态（对齐配额/顺序锁口径）。"""
        self._rate()
        order = self._order_with_pick(qty=50)
        wizard = self._wizard()
        wizard.mes_order_id = order.id
        wizard._onchange_load_report_lines()
        line_b = wizard.report_line_ids.filtered(
            lambda l: l.route_operation_id.operation_id == self.op_b)
        # nothing reported upstream yet -> op_b is sequence-locked
        self.assertTrue(line_b.sequence_locked)
        self.assertEqual(line_b.planned_qty, 50.0)
        self.assertEqual(line_b.remaining_qty, 50.0)
        # report 20 upstream -> cap 20 > 0 reported at op_b -> unlocked
        order.report_operation_qty(self._op_a_row(order), 20.0)
        # sudo-created report rows do not invalidate this env's compute
        # cache: drop it so the counters recompute from the database
        wizard.report_line_ids.invalidate_recordset()
        self.assertFalse(line_b.sequence_locked)
        self.assertEqual(line_b.reported_qty, 0.0)
        line_a = wizard.report_line_ids.filtered(
            lambda l: l.route_operation_id.operation_id == self.op_a)
        self.assertEqual(line_a.reported_qty, 20.0)
        self.assertEqual(line_a.remaining_qty, 30.0)

    def test_wizard_excludes_done_and_station_orders(self):
        """只带出活跃（released/picked/in_progress）report 单。"""
        order = self._order_with_pick(qty=10)
        order.report_operation_qty(self._op_a_row(order), 10.0)
        order.state = 'done'  # out of the active set
        wizard = self._wizard()
        wizard.mes_order_id = order.id
        wizard._onchange_load_report_lines()
        self.assertFalse(wizard.report_line_ids)
        station = self._make_order_common(qty=10, mode='station')
        wizard2 = self._wizard()
        wizard2.mes_order_id = station.id
        wizard2._onchange_load_report_lines()
        self.assertFalse(wizard2.report_line_ids)

    def test_wizard_line_reuse_last_allocation_button(self):
        self._rate()
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0, allocation=(
            (self.emp_zhang, 45.0), (self.emp_li, 55.0)))
        wizard.action_submit_reports()
        wizard2 = self._wizard()
        line = self.env['sn.wsd.piece.report.wizard.line'].create({
            'wizard_id': wizard2.id,
            'mes_order_id': order.id,
            'route_operation_id': self._op_a_row(order).id,
        })
        line.action_reuse_last_allocation()
        self.assertEqual(
            line.participant_ids.mapped('performance_ratio'), [45.0, 55.0])
