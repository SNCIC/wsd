from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

RATE_TYPE_SELECTION = [('piece', '计件（元/件）'), ('hour', '计时（元/小时）')]


class SnWsdPieceRate(models.Model):
    """计件单价扩展「计酬方式」：计件（元/件）或计时（元/小时）。

    主体仍是计件；个别不适合按件衡量的工序（如产量由设备节拍决定的检测、
    调试类工序）可设为计时：工资 = 报工工时 × 小时单价。"""
    _inherit = 'sn.wsd.piece.rate'

    x_rate_type = fields.Selection(
        RATE_TYPE_SELECTION, string='计酬方式', default='piece', required=True,
        help='计件：合格数 × 单价；计时：报工人工工时 × 单价。')


class SnWsdPieceSettlement(models.Model):
    """结算单同时记录件数和工时：

    - x_rate_type：取价时从单价表快照；
    - x_hours：来源报工的人工工时快照（计件单也记录，用于效率与单位工时分析）；
    - 金额：计件 = 合格数 × 单价；计时 = 人工工时 × 单价。
    冻结、作废、月度关账规则沿用计件结算单（确认后 x_hours 一并冻结）。"""
    _inherit = 'sn.wsd.piece.settlement'

    x_rate_type = fields.Selection(
        RATE_TYPE_SELECTION, string='计酬方式', default='piece', copy=False)
    x_hours = fields.Float(string='人工工时(小时)', digits=(10, 2), copy=False)
    x_std_hours = fields.Float(string='标准工时(小时)', digits=(10, 2), copy=False)

    @api.depends('qty_ok', 'price', 'x_rate_type', 'x_hours')
    def _compute_amount(self):
        for settlement in self:
            if settlement.x_rate_type == 'hour':
                settlement.amount = round(settlement.x_hours * settlement.price, 2)
            else:
                settlement.amount = round(settlement.qty_ok * settlement.price, 2)

    def _resolve_rate_price(self):
        res = super()._resolve_rate_price()
        Rate = self.env['sn.wsd.piece.rate'].sudo()
        for settlement in self:
            rate = Rate.search([
                ('company_id', '=', settlement.company_id.id),
                ('product_id', '=', settlement.product_id.id),
                ('operation_id', '=', settlement.operation_id.id),
            ], limit=1)
            rate_type = rate.x_rate_type or 'piece'
            if rate_type == 'hour' and settlement.manage_mode == 'station':
                raise UserError(_('过站口径的结算单按件结算，计时单价请用于报工模式工序。'))
            vals = {'x_rate_type': rate_type}
            report = settlement.operation_report_id
            if report:
                vals['x_hours'] = report.x_man_hours
                vals['x_std_hours'] = report.x_std_hours
            settlement.write(vals)
        return res

    def action_confirm(self):
        for settlement in self:
            if settlement.state == 'draft' and settlement.operation_report_id:
                report = settlement.operation_report_id
                # 草稿期报工工时被修正过 → 以报工最新人工工时为准再确认
                if abs(settlement.x_hours - report.x_man_hours) > 0.0001:
                    settlement.write({'x_hours': report.x_man_hours,
                                      'x_std_hours': report.x_std_hours})
            if settlement.x_rate_type == 'hour' and settlement.x_hours <= 0:
                raise ValidationError(_(
                    '结算单 %s 按计时结算，但来源报工没有工时，请先补录工时。', settlement.name))
        return super().action_confirm()
