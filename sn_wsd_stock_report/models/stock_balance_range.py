from odoo import fields, models

# 报表期间只存一行，由向导写入；SQL 视图会读取这一行作为查询区间。
# 因此该区间是全局共享的（本报表为内部小工具，不做按用户隔离）。
BUSINESS_TIMEZONE = 'Asia/Shanghai'


class SnWsdStockBalanceRange(models.Model):
    _name = 'sn.wsd.stock.balance.range'
    _description = 'Stock Balance Report Date Range'
    _rec_name = 'date_from'

    date_from = fields.Date(string='起始日期', required=True)
    date_to = fields.Date(string='截止日期', required=True)

    def init(self):
        # 保证始终有一行，视图在参数表为空时有兜底，这里补一个默认区间（本月至今）
        self.env.cr.execute(f"""
            INSERT INTO {self._table}
                        (date_from, date_to, create_uid, write_uid, create_date, write_date)
            SELECT date_trunc('month', now() AT TIME ZONE '{BUSINESS_TIMEZONE}')::date,
                   (now() AT TIME ZONE '{BUSINESS_TIMEZONE}')::date,
                   1, 1, now(), now()
            WHERE NOT EXISTS (SELECT 1 FROM {self._table})
        """)

    @classmethod
    def _current(cls, env):
        """返回（必要时创建）唯一的那行区间记录。"""
        record = env['sn.wsd.stock.balance.range'].sudo().search([], order='id', limit=1)
        if not record:
            record = env['sn.wsd.stock.balance.range'].sudo().create({
                'date_from': fields.Date.context_today(env.user).replace(day=1),
                'date_to': fields.Date.context_today(env.user),
            })
        return record
