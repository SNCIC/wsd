from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SnWsdStockBalanceWizard(models.TransientModel):
    _name = 'sn.wsd.stock.balance.wizard'
    _description = 'Stock Balance Report Wizard'

    date_from = fields.Date(
        string='起始日期',
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )
    date_to = fields.Date(
        string='截止日期',
        required=True,
        default=fields.Date.context_today,
    )

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(self.env._('起始日期不能晚于截止日期。'))

    def action_generate(self):
        self.ensure_one()
        self.env['sn.wsd.stock.balance.range']._current(self.env).write({
            'date_from': self.date_from,
            'date_to': self.date_to,
        })
        # Odoo 19 的写入是延迟的，write() 返回时 UPDATE 还没发到数据库，
        # 必须 flush 才能保证紧接着的报表查询读到新区间（Web 请求各自独立事务，
        # 但测试/脚本等在同一环境内连续操作时会踩坑）。
        self.env.flush_all()
        # 同一环境内若已经读过报表，ORM 会缓存行数据，flush 不会清它，需要显式失效。
        self.env['sn.wsd.stock.balance.report'].invalidate_model()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'sn_wsd_stock_report.action_sn_wsd_stock_balance_report'
        )
        action['name'] = self.env._(
            '收发汇总表（%s ~ %s）', self.date_from, self.date_to,
        )
        # 把区间随 action 带到列表上（再随行点击一路传到下钻明细），
        # 这样即使区间参数后来被别人改掉，明细仍按用户看到的这份区间出数。
        action['context'] = {
            'sn_wsd_balance_date_from': str(self.date_from),
            'sn_wsd_balance_date_to': str(self.date_to),
        }
        return action
