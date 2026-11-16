import base64
import io
import re

import xlsxwriter

from odoo import _, fields, models
from odoo.exceptions import UserError

PERIOD_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')
CATEGORY_LABEL = {'production': '生产', 'rework': '返修', 'trial': '试产/调试',
                  'downtime': '停机/异常'}


class PayrollExport(models.TransientModel):
    """导出月度计件计时工资表（Excel）：汇总 + 结算明细 + 工时明细，列固定，供工资/财务系统导入。"""
    _name = 'sn.wsd.payroll.export'
    _description = '导出月度计件计时工资表'

    company_id = fields.Many2one('res.company', string='公司', default=lambda self: self.env.company,
                                 required=True)
    period = fields.Char(string='工资月份', required=True,
                         default=lambda self: fields.Date.context_today(self).strftime('%Y-%m'))
    file_data = fields.Binary(string='文件', readonly=True)
    file_name = fields.Char(string='文件名', readonly=True)

    def _build_xlsx(self):
        self.ensure_one()
        if not PERIOD_RE.match(self.period or ''):
            raise UserError(_('工资月份格式应为 YYYY-MM。'))
        rows = self.env['sn.wsd.payroll.summary'].search([
            ('company_id', '=', self.company_id.id), ('period', '=', self.period)])
        if not rows:
            raise UserError(_('%s 没有已确认的结算或工时。', self.period))
        closed = self.env['sn.wsd.piece.close.log']._month_closed(
            self.company_id, fields.Date.to_date(self.period + '-01'))
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        head = wb.add_format({'bold': True, 'bg_color': '#DCE6F1', 'border': 1})
        money = wb.add_format({'num_format': '#,##0.00', 'border': 1})
        num = wb.add_format({'num_format': '0.00', 'border': 1})
        txt = wb.add_format({'border': 1})

        ws = wb.add_worksheet('工资汇总')
        ws.write(0, 0, '%s %s 月度计件计时汇总（%s；金额只含已确认结算单）' % (
            self.company_id.name, self.period, '已关账' if closed else '未关账'))
        cols = ['工号', '姓名', '计件件数', '计件金额', '计时金额', '应发合计',
                '生产工时', '停机/异常工时', '折合时薪']
        for c, h in enumerate(cols):
            ws.write(2, c, h, head)
        r = 3
        tot = [0.0] * 5
        for row in rows:
            vals = [row.employee_code or '', row.employee_id.name, row.piece_qty, row.piece_amount,
                    row.hour_amount, row.total_amount, row.work_hours, row.downtime_hours,
                    round(row.hourly_income, 2)]
            for c, v in enumerate(vals):
                ws.write(r, c, v, money if c in (3, 4, 5, 8) else (num if c in (2, 6, 7) else txt))
            tot = [tot[0] + row.piece_amount, tot[1] + row.hour_amount, tot[2] + row.total_amount,
                   tot[3] + row.work_hours, tot[4] + row.downtime_hours]
            r += 1
        ws.write(r, 1, '合计', head)
        for c, v in zip((3, 4, 5, 6, 7), tot):
            ws.write(r, c, round(v, 2), money)
        ws.set_column(0, 8, 12)

        date_from = self.period + '-01'
        date_to = str(fields.Date.end_of(fields.Date.to_date(date_from), 'month'))
        ws2 = wb.add_worksheet('结算明细')
        cols2 = ['工号', '姓名', '结算单号', '业务日期', '制令单', '工序', '计酬方式', '合格数',
                 '人工工时', '单价', '结算金额', '本人比例%', '本人件数', '本人工时', '本人金额']
        for c, h in enumerate(cols2):
            ws2.write(0, c, h, head)
        parts = self.env['sn.wsd.piece.settlement.participant'].search([
            ('company_id', '=', self.company_id.id), ('settlement_id.state', '=', 'confirmed'),
            ('settlement_date', '>=', date_from), ('settlement_date', '<=', date_to),
        ], order='employee_id, settlement_date, id')
        for i, p in enumerate(parts, start=1):
            s = p.settlement_id
            vals = [p.employee_code or '', p.employee_id.name, s.name, str(s.date),
                    s.mes_order_id.name, s.route_operation_id.display_label or '',
                    '计时' if s.x_rate_type == 'hour' else '计件', s.qty_ok, s.x_hours, s.price,
                    s.amount, p.performance_ratio, round(p.x_qty_share, 2), p.x_hours, p.amount]
            for c, v in enumerate(vals):
                ws2.write(i, c, v, money if c in (10, 14) else txt)
        ws2.set_column(0, 14, 12)

        ws3 = wb.add_worksheet('工时明细')
        cols3 = ['工号', '姓名', '工时单号', '业务日期', '开始', '结束', '工时', '合格数',
                 '工时类别', '计入人工工时', '制令单', '工序', '工时来源', '补录原因']
        for c, h in enumerate(cols3):
            ws3.write(0, c, h, head)
        entries = self.env['sn.wsd.time.entry'].search([
            ('company_id', '=', self.company_id.id), ('state', '=', 'confirmed'),
            ('date', '>=', date_from), ('date', '<=', date_to)], order='employee_id, date_start')
        src = dict(self.env['sn.wsd.time.entry']._fields['source'].selection)
        for i, e in enumerate(entries, start=1):
            vals = [e.employee_code or '', e.employee_id.name, e.name, str(e.date),
                    e._fmt(e.date_start), e._fmt(e.date_end), e.hours, e.qty_ok,
                    CATEGORY_LABEL.get(e.category, ''), '是' if e.paid else '否',
                    e.mes_order_id.name or '', e.route_operation_id.display_label or '',
                    src.get(e.source, ''), e.manual_reason or '']
            for c, v in enumerate(vals):
                ws3.write(i, c, v, num if c in (6, 7) else txt)
        ws3.set_column(0, 13, 12)
        wb.close()
        return buf.getvalue()

    def action_export(self):
        self.ensure_one()
        data = self._build_xlsx()
        self.write({'file_data': base64.b64encode(data),
                    'file_name': '月度计件计时工资表_%s.xlsx' % self.period})
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/file_data/%s?download=true' % (
                self._name, self.id, self.file_name),
            'target': 'self',
        }
