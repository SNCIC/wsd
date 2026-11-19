from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.sn_wsd_piece_rate.tests.common_piece_rate import PieceRateTestCommon

D = datetime(2026, 8, 12, 0, 0, 0)  # 08:00 Asia/Shanghai


def at(h, m=0):
    return D + timedelta(hours=h, minutes=m)


@tagged('post_install', '-at_install')
class TestPieceTime(PieceRateTestCommon):
    """计件+计时：报工同时记录件数和工时、计酬方式、防重复、冻结、关账、终端计时、分析与汇总。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.tz = 'Asia/Shanghai'
        cls.leader_user = cls.env['res.users'].create({
            'name': 'PT Leader', 'login': 'pt_leader',
            'group_ids': [(4, cls.env.ref('sn_wsd_piece_time.group_time_leader').id)],
        })
        cls.emp_zhang.user_id = cls.leader_user  # 张为班组长
        cls.other_user = cls.env['res.users'].create({
            'name': 'PT Other', 'login': 'pt_other',
            'group_ids': [(4, cls.env.ref('sn_wsd_piece_time.group_time_leader').id)],
        })

    def _order(self, qty=1000):
        order = self._make_order_common(qty=qty, mode='report')
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(self.env, order)
        return order

    def _rep(self, order, qty, start, end, people, op=None, **kw):
        return order.report_operation_with_time(
            self._op_row(order, op or self.op_a), qty, date_start=start, date_end=end,
            participant_vals=people, **kw)

    # ------------------------------------------------------------------
    def test_report_records_qty_and_hours(self):
        self._rate(0.3)
        order = self._order()
        rep = self._rep(order, 100, at(0), at(2), [
            {'employee_id': self.emp_zhang.id, 'performance_ratio': 50},
            {'employee_id': self.emp_li.id, 'performance_ratio': 50}])
        self.assertAlmostEqual(rep.x_duration_hours, 2.0)
        self.assertAlmostEqual(rep.x_man_hours, 4.0)
        self.assertEqual(rep.x_headcount, 2)
        self.assertEqual(len(rep.time_entry_ids), 2)
        self.assertAlmostEqual(sum(rep.time_entry_ids.mapped('qty_ok')), 100)
        st = rep.piece_settlement_ids
        self.assertEqual(len(st), 1)
        self.assertEqual(st.x_rate_type, 'piece')
        self.assertAlmostEqual(st.amount, 30.0)
        self.assertAlmostEqual(st.x_hours, 4.0)
        self.assertEqual(order.x_labor_start, at(0))
        self.assertEqual(order.x_labor_end, at(2))

    def test_duty_and_ratio_allocation(self):
        self._rate(0.3)
        order = self._order()
        rep = self._rep(order, 60, at(0), at(2), [
            {'employee_id': self.emp_zhang.id, 'performance_ratio': 50},
            {'employee_id': self.emp_li.id, 'performance_ratio': 50,
             'duty_start': at(1), 'duty_end': at(2)}])
        hours = {p.employee_id: p.x_work_hours for p in rep.participant_ids}
        self.assertAlmostEqual(hours[self.emp_zhang], 2.0)
        self.assertAlmostEqual(hours[self.emp_li], 1.0)
        self.assertAlmostEqual(rep.x_man_hours, 3.0)
        rep2 = self._rep(order, 40, at(3), at(5), [
            {'employee_id': self.emp_zhang.id, 'performance_ratio': 60},
            {'employee_id': self.emp_li.id, 'performance_ratio': 40}], alloc='ratio')
        hours = {p.employee_id: p.x_work_hours for p in rep2.participant_ids}
        self.assertAlmostEqual(hours[self.emp_zhang], 2.4)
        self.assertAlmostEqual(hours[self.emp_li], 1.6)

    def test_hour_rate_operation(self):
        rate = self._rate(30.0)
        rate.x_rate_type = 'hour'
        order = self._order()
        rep = self._rep(order, 50, at(0), at(2), [
            {'employee_id': self.emp_zhang.id, 'performance_ratio': 50},
            {'employee_id': self.emp_li.id, 'performance_ratio': 50,
             'duty_start': at(1), 'duty_end': at(2)}])
        st = rep.piece_settlement_ids
        self.assertEqual(st.x_rate_type, 'hour')
        self.assertAlmostEqual(st.amount, 90.0)  # 3 人时 × 30
        amounts = {p.employee_id: p.amount for p in st.participant_ids}
        self.assertAlmostEqual(amounts[self.emp_zhang], 60.0)
        self.assertAlmostEqual(amounts[self.emp_li], 30.0)
        st.action_confirm()
        self.assertEqual(st.state, 'confirmed')

    def test_no_double_hours_same_employee(self):
        self._rate(0.3)
        order = self._order()
        self._rep(order, 10, at(0), at(2), [{'employee_id': self.emp_zhang.id, 'performance_ratio': 100}])
        with self.assertRaises(ValidationError):
            self._rep(order, 10, at(1), at(3), [{'employee_id': self.emp_zhang.id, 'performance_ratio': 100}],
                      op=self.op_b)
        # 手工补录与报工重叠同样拒绝
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.time.entry'].create({
                'employee_id': self.emp_zhang.id, 'category': 'rework', 'mes_order_id': order.id,
                'date_start': at(1, 30), 'date_end': at(2, 30), 'source': 'manual',
                'manual_reason': '补录'})

    def test_confirm_freezes_hours(self):
        self._rate(0.3)
        order = self._order()
        rep = self._rep(order, 10, at(0), at(2), [
            {'employee_id': self.emp_zhang.id, 'performance_ratio': 50},
            {'employee_id': self.emp_li.id, 'performance_ratio': 50}])
        # 草稿期可改工时，结算单工时随之更新
        rep.x_date_end = at(3)
        st = rep.piece_settlement_ids
        st.action_confirm()
        self.assertAlmostEqual(st.x_hours, 6.0)
        with self.assertRaises(UserError):
            rep.x_date_end = at(4)
        with self.assertRaises(UserError):
            rep.time_entry_ids[0].hours = 1.0
        with self.assertRaises(UserError):
            rep.participant_ids[0].x_hours_input = 1.0

    def test_month_close_blocks_hours(self):
        self._rate(0.3)
        order = self._order()
        rep = self._rep(order, 10, at(0), at(2), [{'employee_id': self.emp_zhang.id, 'performance_ratio': 100}])
        self.env['sn.wsd.piece.close.wizard'].create({
            'period': '2026-08', 'acknowledge_drafts': True}).action_close()
        with self.assertRaises(UserError):
            rep.x_date_start = at(0, 30)
        with self.assertRaises(UserError):
            self.env['sn.wsd.time.entry'].create({
                'employee_id': self.emp_li.id, 'category': 'trial', 'mes_order_id': order.id,
                'date_start': at(5), 'date_end': at(6), 'source': 'manual', 'manual_reason': '补录'})

    def test_manual_entry_reason_and_leader_confirm(self):
        order = self._order()
        Entry = self.env['sn.wsd.time.entry']
        with self.assertRaises(ValidationError):
            Entry.create({'employee_id': self.emp_li.id, 'category': 'rework', 'mes_order_id': order.id,
                          'date_start': at(5), 'date_end': at(6), 'source': 'manual'})
        entry = Entry.create({'employee_id': self.emp_li.id, 'category': 'rework',
                              'mes_order_id': order.id, 'date_start': at(5), 'date_end': at(6),
                              'source': 'manual', 'manual_reason': '终端离线未计时'})
        self.assertEqual(entry.state, 'to_confirm')
        with self.assertRaises(UserError):
            entry.with_user(self.other_user).action_leader_confirm()
        entry.with_user(self.leader_user).action_leader_confirm()
        self.assertEqual(entry.state, 'confirmed')
        self.assertEqual(entry.confirmed_by, self.leader_user)

    def test_downtime_not_paid_and_separate(self):
        order = self._order()
        entry = self.env['sn.wsd.time.entry'].create({
            'employee_id': self.emp_li.id, 'category': 'downtime', 'mes_order_id': order.id,
            'date_start': at(7), 'date_end': at(8), 'source': 'manual', 'manual_reason': '贴片机抛料停线',
            'downtime_reason': 'equipment'})
        entry.action_leader_confirm()
        self.assertFalse(entry.paid)
        self.env['sn.wsd.time.entry'].flush_model()
        cost = self.env['sn.wsd.labor.cost'].search([('mes_order_id', '=', order.id)])
        self.assertAlmostEqual(cost.downtime_hours, 1.0)
        self.assertAlmostEqual(cost.man_hours, 0.0)

    def test_terminal_timer(self):
        self._rate(0.3)
        order = self._order()
        Timer = self.env['sn.wsd.work.timer']
        row = self._op_a_row(order)
        timer = Timer.start(self.emp_zhang, order, row, participants=self.emp_li, at=at(0))
        with self.assertRaises(ValidationError):
            Timer.start(self.emp_zhang, order, self._op_row(order, self.op_b), at=at(0, 5))
        timer.action_pause(at=at(1))
        timer.action_resume(at=at(1, 30))
        rep = timer.action_finish_report(80, at=at(2))
        self.assertEqual(timer.state, 'done')
        self.assertEqual(timer.timer_seconds, 5400)
        self.assertAlmostEqual(rep.x_duration_hours, 1.5)
        self.assertAlmostEqual(rep.x_man_hours, 3.0)
        self.assertEqual(rep.x_hours_source, 'terminal')
        self.assertEqual(set(rep.time_entry_ids.mapped('source')), {'terminal'})
        self.assertAlmostEqual(rep.piece_settlement_ids.amount, 24.0)

    def test_workbench_submit_with_hours(self):
        self._rate(0.3)
        order = self._order()
        Wb = self.env['sn.wsd.piece.settlement.generate.wizard']
        payload = [{
            'mes_order_id': order.id, 'route_operation_id': self._op_a_row(order).id,
            'qty_ok': 20, 'qty_ng': 0, 'qty_scrap': 0, 'team_id': False,
            'x_date_start': '2026-08-12T08:00', 'x_date_end': '2026-08-12T10:30', 'x_hours': 0,
            'participants': [{'employee_id': self.emp_zhang.id, 'performance_ratio': 100,
                              'x_work_hours': 0}],
        }]
        Wb.submit_workbench(payload)
        rep = self.env['sn.wsd.mes.operation.report'].search([('mes_order_id', '=', order.id)])
        self.assertEqual(rep.x_date_start, at(0))
        self.assertAlmostEqual(rep.x_man_hours, 2.5)
        self.assertEqual(rep.x_hours_source, 'workbench')
        # 开启「报工必须记工时」后，未填工时被拦
        self.env['ir.config_parameter'].sudo().set_param('sn_wsd_piece_time.require_hours', '1')
        payload[0].update({'x_date_start': '', 'x_date_end': '', 'qty_ok': 5})
        with self.assertRaises(ValidationError):
            Wb.submit_workbench(payload)
        # 只填工时也可以
        payload[0]['x_hours'] = 1.0
        Wb.submit_workbench(payload)

    def test_analysis_cost_payroll_export(self):
        self._rate(0.3)
        self._rate(0.5, operation=self.op_b)
        self._op_a_row(self.order).time_cycle_manual = 36.0  # 36 秒/件
        order = self._order()
        self._op_a_row(order).time_cycle_manual = 36.0
        r1 = self._rep(order, 100, at(0), at(2), [
            {'employee_id': self.emp_zhang.id, 'performance_ratio': 60},
            {'employee_id': self.emp_li.id, 'performance_ratio': 40}])
        r2 = self._rep(order, 100, at(2), at(3), [
            {'employee_id': self.emp_zhang.id, 'performance_ratio': 100}], op=self.op_b)
        (r1 | r2).piece_settlement_ids.action_confirm()
        self.env.flush_all()
        ana = self.env['sn.wsd.labor.analysis'].search([
            ('mes_order_id', '=', order.id), ('route_operation_id', '=', self._op_a_row(order).id)])
        self.assertAlmostEqual(ana.man_hours, 4.0)
        self.assertAlmostEqual(ana.std_hours, 1.0)
        self.assertAlmostEqual(ana.efficiency, 25.0)
        self.assertAlmostEqual(ana.uph, 25.0)
        self.assertAlmostEqual(ana.piece_amount, 30.0)
        cost = self.env['sn.wsd.labor.cost'].search([('mes_order_id', '=', order.id)])
        self.assertAlmostEqual(cost.labor_amount, 80.0)
        self.assertAlmostEqual(cost.man_hours, 5.0)
        self.assertAlmostEqual(cost.completed_qty, order.x_output_qty)
        if order.x_output_qty:
            self.assertAlmostEqual(cost.unit_cost, round(80.0 / order.x_output_qty, 4))
        period = fields.Date.context_today(self.env.user).strftime('%Y-%m')
        rows = self.env['sn.wsd.payroll.summary'].search([('employee_id', '=', self.emp_zhang.id)])
        piece_row = rows.filtered(lambda r: r.period == period)
        self.assertAlmostEqual(piece_row.piece_amount, 18.0 + 50.0)
        self.assertAlmostEqual(piece_row.piece_qty, 160.0)
        hours_row = rows.filtered(lambda r: r.period == '2026-08')
        self.assertAlmostEqual(hours_row.work_hours, 3.0)
        export = self.env['sn.wsd.payroll.export'].create({'period': period})
        data = export._build_xlsx()
        self.assertTrue(data[:2] == b'PK')
