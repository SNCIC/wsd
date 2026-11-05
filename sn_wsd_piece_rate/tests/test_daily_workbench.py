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
                     team=None, allocation=(), new_price=0.0):
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
            'x_new_price': new_price,
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

    def test_submit_without_rate_blocked_until_price_typed(self):
        """未配单价且未现填 → 整批拦截，零落库（不再产生待分配积压）。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0, allocation=(
            (self.emp_zhang, 100.0),))
        with self.assertRaises(ValidationError) as ctx:
            wizard.action_submit_reports()
        self.assertIn('enter the unit price', str(ctx.exception))
        self.assertFalse(self._reports(order))
        self.assertFalse(self.env['sn.wsd.piece.rate'].search([
            ('product_id', '=', order.product_id.id)]))

    def test_submit_typed_price_requires_participants(self):
        """未配单价但现填了价：参与人同口径强制（enforce，独立文案）。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0,
                          new_price=0.25)
        with self.assertRaises(ValidationError) as ctx:
            wizard.action_submit_reports()
        self.assertIn('select the participants', str(ctx.exception))
        self.assertFalse(self._reports(order))

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
        self._rate(operation=self.op_b)
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

    def test_menu_server_action_makes_line_buttons_safe(self):
        """菜单 server action 路径：create 后 action_reload_lines 先落库，
        行级快捷按钮（均分等）在真实行上可调用——修复未保存向导上
        点按钮报 wizard_id 缺失的问题。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        wizard.action_reload_lines()
        lines = wizard.report_line_ids.filtered(
            lambda l: l.mes_order_id == order)
        self.assertTrue(lines)
        self.assertTrue(lines[0].wizard_id)
        line = lines[0]
        line.participant_ids = [(5, 0, 0), (0, 0, {
            'employee_id': self.emp_zhang.id, 'performance_ratio': 0.0,
        }), (0, 0, {
            'employee_id': self.emp_li.id, 'performance_ratio': 0.0,
        })]
        line.action_equal_split()
        self.assertEqual(
            sorted(line.participant_ids.mapped('performance_ratio')),
            [50.0, 50.0])

    def test_onchange_team_fills_and_lock_rebalance(self):
        """显式锁定口径（2026-11-01 用户定稿方案2）：选班组带出成员并归一化
        （锁定全清）；锁定某行后其余行均分剩余；均分按钮全员均分并清锁。
        手输超过 100 的值被即时约束拦下（test_ratio_total_cannot_exceed_100），
        故大值场景用 skip 标记模拟锁定前的过渡态。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        line = self._wizard_line(wizard, order, self.op_a, team=self.team)
        line._fill_from_team()
        self.assertEqual(
            line.participant_ids.mapped('employee_id'),
            self.team.member_ids.mapped('employee_id'))
        self.assertEqual(
            sorted(line.participant_ids.mapped('performance_ratio')),
            [20.0, 20.0, 30.0, 30.0])
        self.assertFalse(any(line.participant_ids.mapped('x_ratio_locked')))
        # lock one 30% row at 60%: the three unlocked rows equally split 40
        zhang = line.participant_ids.filtered(
            lambda p: p.employee_id == self.emp_zhang)
        zhang.with_context(sn_wsd_skip_ratio_check=True).write(
            {'performance_ratio': 60.0, 'x_ratio_locked': True})
        line._rebalance_participants()
        self.assertEqual(
            sorted(line.participant_ids.mapped('performance_ratio')),
            [13.3333, 13.3333, 13.3334, 60.0])
        # equal split button: everyone equal again, locks cleared
        line.action_equal_split()
        self.assertEqual(
            sorted(line.participant_ids.mapped('performance_ratio')),
            [25.0, 25.0, 25.0, 25.0])
        self.assertFalse(any(line.participant_ids.mapped('x_ratio_locked')))

    def test_ratio_total_cannot_exceed_100(self):
        """即时约束（2026-11-01）：单行 0–100、行合计 ≤100，保存即拦，
        不用等提交；重分配路径（均分/锁定重摊）不受中间态影响。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        line = self._wizard_line(wizard, order, self.op_a, allocation=(
            (self.emp_zhang, 60.0), (self.emp_li, 40.0)))
        with self.assertRaises(ValidationError) as ctx:
            line.participant_ids[1].performance_ratio = 50.0  # 60+50=110
        self.assertIn('cannot exceed 100', str(ctx.exception))
        with self.assertRaises(ValidationError):
            line.participant_ids[1].performance_ratio = -5.0
        # rebalance paths still work through the intermediate states
        line.participant_ids[1].with_context(
            sn_wsd_skip_ratio_check=True).performance_ratio = 40.0
        line.action_equal_split()
        self.assertEqual(
            sorted(line.participant_ids.mapped('performance_ratio')),
            [50.0, 50.0])
        line.participant_ids[0].x_ratio_locked = True
        line._rebalance_participants()
        self.assertEqual(
            sorted(line.participant_ids.mapped('performance_ratio')),
            [50.0, 50.0])

    def test_ratio_total_compute_and_lock_toggle(self):
        """即时约束下新增行只能带来 ≤100 的值；锁定行保持、其余均分。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        line = self._wizard_line(wizard, order, self.op_a, allocation=(
            (self.emp_zhang, 50.0), (self.emp_li, 50.0)))
        self.assertAlmostEqual(line.ratio_total, 100.0)
        # a new row pushing the total over 100 is blocked at create
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.piece.report.wizard.participant'].create({
                'line_id': line.id, 'employee_id': self.emp_wang.id,
                'performance_ratio': 33.3333,
            })
        # add wang within the budget, then lock zhang: li and wang split 50
        self.env['sn.wsd.piece.report.wizard.participant'].create({
            'line_id': line.id, 'employee_id': self.emp_wang.id,
            'performance_ratio': 0.0,
        })
        zhang = line.participant_ids.filtered(
            lambda p: p.employee_id == self.emp_zhang)
        zhang.x_ratio_locked = True
        line._rebalance_participants()
        self.assertAlmostEqual(line.ratio_total, 100.0)
        self.assertEqual(
            sorted(line.participant_ids.mapped('performance_ratio')),
            [25.0, 25.0, 50.0])

    # ------------------------------------------------------------------
    # OWL workbench API: payload in, payload out (all gates server-side)
    # ------------------------------------------------------------------

    def test_workbench_data_and_submit(self):
        """OWL 工作台链路：get_workbench_data 带出进度/单价/预填参与人；
        submit_workbench 用客户端载荷走同一提交核心（闸/建价/草稿）。"""
        self._rate(price=0.3)
        order = self._order_with_pick(qty=100)
        Wizard = self.env['sn.wsd.piece.settlement.generate.wizard']
        data = Wizard.get_workbench_data()
        mine = [l for l in data['lines'] if l['mes_order_id'] == order.id]
        self.assertEqual(len(mine), 2)  # one per route operation
        line = next(l for l in mine
                    if l['route_operation_id'] == self._op_a_row(order).id)
        self.assertAlmostEqual(line['piece_price'], 0.3)
        self.assertEqual(line['planned_qty'], 100.0)
        self.assertIn('team_id', line)
        self.assertTrue(any(t['members'] for t in data['teams']))
        count = Wizard.submit_workbench([{
            'mes_order_id': order.id,
            'route_operation_id': line['route_operation_id'],
            'qty_ok': 10.0,
            'qty_ng': 0.0,
            'qty_scrap': 0.0,
            'scrap_reason_id': False,
            'x_new_price': 0.0,
            'team_id': False,
            'participants': [{
                'employee_id': self.emp_zhang.id,
                'performance_ratio': 100.0,
                'x_ratio_locked': False,
            }],
        }])
        self.assertEqual(count, 1)
        report = self._reports(order)
        self.assertEqual(report.qty_ok, 10.0)
        self.assertEqual(
            report.participant_ids.mapped('performance_ratio'), [100.0])
        settlement = report.piece_settlement_ids
        self.assertAlmostEqual(settlement.price, 0.3)
        self.assertAlmostEqual(settlement.amount, 3.0)
        with self.assertRaises(UserError):
            Wizard.submit_workbench([])

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
        """终端式直调（不传分配）向后兼容：返回新报工行、不建草稿、
        行留台账「未结算」，走台账批量生成通道补结算。"""
        self._rate()
        order = self._order_with_pick(qty=100)
        report = order.report_operation_qty(
            self._op_a_row(order), 5.0)
        self.assertEqual(len(report), 1)
        self.assertEqual(report.qty_ok, 5.0)
        self.assertFalse(report.participant_ids)
        self.assertFalse(report.piece_settlement_ids)
        self.assertFalse(report.x_piece_settled)

    # ------------------------------------------------------------------
    # typed price: rate master creation at submit (report-daily-price-inline)
    # ------------------------------------------------------------------

    def test_submit_new_price_creates_rate_and_draft(self):
        """现填单价：提交建入主数据 + 草稿按现填价计 + 下次行上只读带出。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=100.0, allocation=(
            (self.emp_zhang, 45.0), (self.emp_li, 55.0)), new_price=0.25)
        wizard.action_submit_reports()
        rate = self.env['sn.wsd.piece.rate'].search([
            ('company_id', '=', self.env.company.id),
            ('product_id', '=', order.product_id.id),
            ('operation_id', '=', self.op_a.id),
        ])
        self.assertEqual(len(rate), 1)
        self.assertAlmostEqual(rate.price, 0.25)
        report = self._reports(order)
        settlement = report.piece_settlement_ids
        self.assertEqual(len(settlement), 1)
        self.assertAlmostEqual(settlement.price, 0.25)
        self.assertAlmostEqual(settlement.amount, 25.0)
        self.assertTrue(report.x_piece_settled)
        # the next wizard line resolves the new rate read-only
        line = self.env['sn.wsd.piece.report.wizard.line'].create({
            'wizard_id': self._wizard().id,
            'mes_order_id': order.id,
            'route_operation_id': self._op_a_row(order).id,
        })
        self.assertAlmostEqual(line.piece_price, 0.25)

    def test_submit_new_price_two_lines_single_rate(self):
        """同批两行同（产品, 工序）都未配价：只建一张价，两笔草稿同价。"""
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=60.0, allocation=(
            (self.emp_zhang, 100.0),), new_price=0.25)
        self._wizard_line(wizard, order, self.op_a, qty_ok=40.0, allocation=(
            (self.emp_li, 100.0),), new_price=0.40)
        wizard.action_submit_reports()
        rate = self.env['sn.wsd.piece.rate'].search([
            ('product_id', '=', order.product_id.id),
            ('operation_id', '=', self.op_a.id),
        ])
        self.assertEqual(len(rate), 1)
        self.assertAlmostEqual(rate.price, 0.25)  # first line wins
        prices = self._reports(order).mapped(
            lambda r: r.piece_settlement_ids.price)
        self.assertEqual(prices, [0.25, 0.25])

    def test_submit_existing_rate_ignores_typed_price(self):
        """已配价行上现填的价被忽略：主数据不动，草稿按主数据价计。"""
        self._rate(price=0.3)
        order = self._order_with_pick(qty=100)
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0, allocation=(
            (self.emp_zhang, 100.0),), new_price=0.9)
        wizard.action_submit_reports()
        rate = self.env['sn.wsd.piece.rate'].search([
            ('product_id', '=', order.product_id.id),
            ('operation_id', '=', self.op_a.id),
        ])
        self.assertAlmostEqual(rate.price, 0.3)
        settlement = self._reports(order).piece_settlement_ids
        self.assertAlmostEqual(settlement.price, 0.3)
        self.assertAlmostEqual(settlement.amount, 3.0)

    def test_submit_month_closed_with_new_price_creates_rate_only(self):
        """关账月现填价：单价主数据照建，草稿不开、行留台账未结算。"""
        order = self._order_with_pick(qty=100)
        self.env['sn.wsd.piece.close.log'].create({
            'company_id': self.env.company.id,
            'period': self.env['sn.wsd.piece.close.log']._period_of(
                fields.Date.today()),
            'action': 'close',
        })
        wizard = self._wizard()
        self._wizard_line(wizard, order, self.op_a, qty_ok=10.0, allocation=(
            (self.emp_zhang, 100.0),), new_price=0.2)
        wizard.action_submit_reports()  # no error raised
        rate = self.env['sn.wsd.piece.rate'].search([
            ('product_id', '=', order.product_id.id),
            ('operation_id', '=', self.op_a.id),
        ])
        self.assertAlmostEqual(rate.price, 0.2)
        report = self._reports(order)
        self.assertFalse(report.piece_settlement_ids)
        self.assertFalse(report.x_piece_settled)

    # ------------------------------------------------------------------
    # ledger batch generation (former To-Allocate tab)
    # ------------------------------------------------------------------

    def test_ledger_generate_settlement_team_default(self):
        """台账批量生成：无分配的终端行 → 班组默认参与人带出、单价解析。"""
        self._rate(price=0.3)
        order = self._order_with_pick(qty=100)
        report = order.report_operation_qty(
            self._op_a_row(order), 5.0)  # terminal-style, no allocation
        result = report.action_generate_piece_settlement()
        self.assertEqual(result['res_model'], 'sn.wsd.piece.settlement')
        settlement = report.piece_settlement_ids
        self.assertEqual(len(settlement), 1)
        self.assertAlmostEqual(settlement.price, 0.3)
        self.assertAlmostEqual(settlement.qty_ok, 5.0)
        # the order's line has exactly one active team -> members normalized
        self.assertEqual(settlement.team_id, self.team)
        self.assertEqual(
            sorted(settlement.participant_ids.mapped('performance_ratio')),
            [20.0, 20.0, 30.0, 30.0])
        self.assertTrue(report.x_piece_settled)
        # regenerating the now-settled row is clearly rejected
        with self.assertRaises(UserError) as ctx:
            report.action_generate_piece_settlement()
        self.assertIn('already has a non-void piece settlement',
                      str(ctx.exception))

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
        """作废释放后补生成（台账通道）：新草稿复制最新分配，作废单留痕不变。"""
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
        report.action_generate_piece_settlement()
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
