import calendar

from odoo import _, fields, models, tools


class SnWsdPayrollSummary(models.Model):
    """员工月度计件计时汇总（工资依据）：件数、工时、金额同表。

    口径：金额 = 已确认结算单的参与人实得（计件 / 计时分列）；件数 = 已确认计件
    结算单合格数 × 本人比例；工时 = 已确认工时记录（生产含返修/试产，与停机/异常工时分列）。"""
    _name = 'sn.wsd.payroll.summary'
    _description = '员工月度计件计时汇总'
    _auto = False
    _order = 'period desc, employee_code, employee_id'

    company_id = fields.Many2one('res.company', string='公司', readonly=True)
    period = fields.Char(string='工资月份', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='员工', readonly=True)
    employee_code = fields.Char(string='工号', readonly=True)
    piece_qty = fields.Float(string='计件件数', digits=(12, 1), readonly=True)
    piece_amount = fields.Float(string='计件金额', digits=(12, 2), readonly=True)
    hour_amount = fields.Float(string='计时金额', digits=(12, 2), readonly=True)
    work_hours = fields.Float(string='生产工时', digits=(10, 2), readonly=True)
    downtime_hours = fields.Float(string='停机/异常工时', digits=(10, 2), readonly=True)
    total_amount = fields.Float(string='应发合计', digits=(12, 2), readonly=True)
    hourly_income = fields.Float(string='折合时薪', digits=(10, 2), readonly=True,
                                 help='应发合计 ÷ 生产工时，用于与最低工资、同岗位比较')
    month_closed = fields.Boolean(string='已关账', compute='_compute_month_closed')

    def _compute_month_closed(self):
        CloseLog = self.env['sn.wsd.piece.close.log']
        for row in self:
            row.month_closed = CloseLog._month_closed(
                row.company_id, fields.Date.to_date(row.period + '-01')) if row.period else False

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
            WITH p AS (
                SELECT s.company_id, to_char(sp.settlement_date, 'YYYY-MM') AS period, sp.employee_id,
                       SUM(CASE WHEN COALESCE(s.x_rate_type, 'piece') = 'piece'
                                THEN s.qty_ok * sp.performance_ratio / 100.0 ELSE 0 END) AS piece_qty,
                       SUM(CASE WHEN COALESCE(s.x_rate_type, 'piece') = 'piece' THEN sp.amount ELSE 0 END) AS piece_amount,
                       SUM(CASE WHEN s.x_rate_type = 'hour' THEN sp.amount ELSE 0 END) AS hour_amount
                  FROM sn_wsd_piece_settlement_participant sp
                  JOIN sn_wsd_piece_settlement s ON s.id = sp.settlement_id
                 WHERE s.state = 'confirmed'
                 GROUP BY 1, 2, 3
            ), t AS (
                SELECT e.company_id, to_char(e.date, 'YYYY-MM') AS period, e.employee_id,
                       SUM(CASE WHEN e.category != 'downtime' THEN e.hours ELSE 0 END) AS work_hours,
                       SUM(CASE WHEN e.category = 'downtime' THEN e.hours ELSE 0 END) AS downtime_hours
                  FROM sn_wsd_time_entry e
                 WHERE e.state = 'confirmed'
                 GROUP BY 1, 2, 3
            ), k AS (
                SELECT company_id, period, employee_id FROM p
                UNION SELECT company_id, period, employee_id FROM t
            )
            SELECT row_number() OVER (ORDER BY k.period, k.employee_id) AS id,
                   k.company_id, k.period, k.employee_id, e.barcode AS employee_code,
                   COALESCE(p.piece_qty, 0) AS piece_qty,
                   COALESCE(p.piece_amount, 0) AS piece_amount,
                   COALESCE(p.hour_amount, 0) AS hour_amount,
                   COALESCE(t.work_hours, 0) AS work_hours,
                   COALESCE(t.downtime_hours, 0) AS downtime_hours,
                   COALESCE(p.piece_amount, 0) + COALESCE(p.hour_amount, 0) AS total_amount,
                   CASE WHEN COALESCE(t.work_hours, 0) > 0
                        THEN (COALESCE(p.piece_amount, 0) + COALESCE(p.hour_amount, 0)) / t.work_hours
                        ELSE 0 END AS hourly_income
              FROM k
              JOIN hr_employee e ON e.id = k.employee_id
              LEFT JOIN p ON p.company_id = k.company_id AND p.period = k.period AND p.employee_id = k.employee_id
              LEFT JOIN t ON t.company_id = k.company_id AND t.period = k.period AND t.employee_id = k.employee_id
            )""" % self._table)

    def _period_range(self):
        self.ensure_one()
        year, month = map(int, self.period.split('-'))
        return ('%04d-%02d-01' % (year, month),
                '%04d-%02d-%02d' % (year, month, calendar.monthrange(year, month)[1]))

    def action_view_piece(self):
        self.ensure_one()
        date_from, date_to = self._period_range()
        return {
            'type': 'ir.actions.act_window',
            'name': _('结算明细：%(emp)s %(period)s', emp=self.employee_id.name, period=self.period),
            'res_model': 'sn.wsd.piece.settlement.participant',
            'view_mode': 'list',
            'views': [(self.env.ref('sn_wsd_piece_time.view_payroll_piece_line_list').id, 'list')],
            'domain': [('employee_id', '=', self.employee_id.id),
                       ('settlement_id.state', '=', 'confirmed'),
                       ('settlement_date', '>=', date_from), ('settlement_date', '<=', date_to)],
        }

    def action_view_time(self):
        self.ensure_one()
        date_from, date_to = self._period_range()
        return {
            'type': 'ir.actions.act_window',
            'name': _('工时明细：%(emp)s %(period)s', emp=self.employee_id.name, period=self.period),
            'res_model': 'sn.wsd.time.entry', 'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.employee_id.id), ('state', '=', 'confirmed'),
                       ('date', '>=', date_from), ('date', '<=', date_to)],
        }


class SnWsdPieceSettlementParticipant(models.Model):
    _inherit = 'sn.wsd.piece.settlement.participant'

    x_rate_type = fields.Selection(related='settlement_id.x_rate_type', string='计酬方式')
    x_unit_price = fields.Float(related='settlement_id.price', string='单价')
    x_hours = fields.Float(string='本人工时', digits=(10, 2), compute='_compute_x_hours')
    x_qty_share = fields.Float(string='本人件数', digits=(12, 1), compute='_compute_x_hours')

    def _compute_x_hours(self):
        for p in self:
            rep = p.settlement_id.operation_report_id
            part = rep.participant_ids.filtered(lambda x: x.employee_id == p.employee_id)[:1]
            p.x_hours = part.x_work_hours if part else 0.0
            p.x_qty_share = p.settlement_id.qty_ok * p.performance_ratio / 100.0
