from odoo import fields, models
from odoo.tools import drop_view_if_exists

# stock_move_line.date 存的是 UTC naive 时间戳，期间归属必须换算到业务时区，
# 否则每天 0:00-8:00 的流水会被算到前一天（进而落到区间外）。
BUSINESS_TIMEZONE = 'Asia/Shanghai'


class SnWsdStockBalanceReport(models.Model):
    """收发汇总表（库存收发存，按数量）。

    统计口径：

    * 只统计仓库库存区（``stock.warehouse.lot_stock_id`` 及其子树，即 WH/库存）内的物料；
      行粒度是「物料 × 仓库」。
    * 收入 = 目标库位在库存区内、来源库位在库存区外的流水；
      发出 = 来源库位在库存区内、目标库位在库存区外的流水。
    * 库内调拨（两端都在库存区内）不计收入与发出。
    * 查询区间由 ``sn.wsd.stock.balance.range`` 的唯一一行决定，由向导写入；
      期初 = 区间开始日之前的累计净流入，结存 = 区间结束日（含当日）之前的累计净流入。
      因为库存区总量是守恒量，期末结存即累计净流入，所以无需期初快照表。

    本视图不自己拼流水，而是从 ``sn.wsd.stock.balance.detail``（下钻明细）聚合，
    保证点击某行看到的明细与列表里的数字完全对得上。
    """

    _name = 'sn.wsd.stock.balance.report'
    _description = 'Stock In/Out Balance Report'
    _auto = False
    _rec_name = 'default_code'
    _order = 'default_code, warehouse_id'

    warehouse_id = fields.Many2one('stock.warehouse', string='仓库', readonly=True)
    product_id = fields.Many2one('product.product', string='物料', readonly=True)
    default_code = fields.Char(string='物料编码', readonly=True)
    product_name = fields.Char(string='物料名称', readonly=True)
    material_specification = fields.Char(string='规格型号', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='单位', readonly=True)
    qty_initial = fields.Float(
        string='期初数量', readonly=True, digits='Product Unit',
    )
    qty_in = fields.Float(
        string='收入数量', readonly=True, digits='Product Unit',
    )
    qty_out = fields.Float(
        string='发出数量', readonly=True, digits='Product Unit',
    )
    qty_balance = fields.Float(
        string='结存数量', readonly=True, digits='Product Unit',
    )

    def init(self):
        # 参数表与本视图在同一批初始化中，先后顺序无法保证，这里显式确保它已建表
        self.env['sn.wsd.stock.balance.range']._auto_init()
        # 汇总的流水口径全部来自明细视图，必须先建好它
        self.env['sn.wsd.stock.balance.detail'].init()
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH param AS (
                    -- 参数表为空时兜底为「本月至今」，保证视图始终有一行可用
                    SELECT COALESCE(
                               (SELECT date_range.date_from
                                FROM sn_wsd_stock_balance_range date_range
                                ORDER BY date_range.id LIMIT 1),
                               date_trunc('month', now() AT TIME ZONE '{BUSINESS_TIMEZONE}')::date
                           ) AS date_from,
                           COALESCE(
                               (SELECT date_range.date_to
                                FROM sn_wsd_stock_balance_range date_range
                                ORDER BY date_range.id LIMIT 1),
                               (now() AT TIME ZONE '{BUSINESS_TIMEZONE}')::date
                           ) AS date_to
                ),
                summary AS (
                    -- 按明细的方向归集：期内收入 / 期内发出 / 期初（区间开始日之前的净流入）
                    SELECT detail.product_id,
                           detail.warehouse_id,
                           sum(CASE WHEN detail.date < param.date_from
                                    THEN CASE detail.direction
                                             WHEN 'in' THEN detail.quantity
                                             ELSE -detail.quantity
                                         END
                                    ELSE 0 END) AS qty_initial,
                           sum(CASE WHEN detail.date >= param.date_from
                                     AND detail.date <= param.date_to
                                     AND detail.direction = 'in'
                                    THEN detail.quantity ELSE 0 END) AS qty_in,
                           sum(CASE WHEN detail.date >= param.date_from
                                     AND detail.date <= param.date_to
                                     AND detail.direction = 'out'
                                    THEN detail.quantity ELSE 0 END) AS qty_out
                    FROM sn_wsd_stock_balance_detail detail
                    CROSS JOIN param
                    GROUP BY detail.product_id, detail.warehouse_id, param.date_from, param.date_to
                )
                SELECT
                       -- 行 id 直接用「物料 × 仓库」编出来，不用 row_number()：
                       -- 报表行集合会随区间内物料进出（新物料入库、结存归零）而变化，
                       -- 行号一漂移，用户点开的就是另一颗物料的明细。仓库数 < 1000、
                       -- 物料 id < 2147483（超出会整数溢出报错，不会静默串行）即可。
                       summary.product_id * 1000 + summary.warehouse_id AS id,
                       summary.warehouse_id,
                       summary.product_id,
                       product.default_code,
                       COALESCE(template.name->>'zh_CN', template.name->>'en_US') AS product_name,
                       template.material_specification,
                       template.uom_id,
                       summary.qty_initial,
                       summary.qty_in,
                       summary.qty_out,
                       summary.qty_initial + summary.qty_in - summary.qty_out AS qty_balance
                FROM summary
                JOIN product_product product ON product.id = summary.product_id
                JOIN product_template template ON template.id = product.product_tmpl_id
                -- 区间内有收发、或期末仍有结存的物料才出报表行
                WHERE summary.qty_in <> 0
                   OR summary.qty_out <> 0
                   OR summary.qty_initial + summary.qty_in - summary.qty_out <> 0
                ORDER BY product.default_code, summary.warehouse_id
            )
        """)

    def _report_period(self):
        """报表区间：优先取生成报表时写进 action context 的那一份。

        列表是 SQL 视图的实时快照，而参数表是全局共享的（别人期间换一个区间就会改），
        所以下钻要用生成时的那份区间，才对得上用户眼前看到的数字；取不到再回落到参数表。
        """
        self.ensure_one()
        date_from = self.env.context.get('sn_wsd_balance_date_from')
        date_to = self.env.context.get('sn_wsd_balance_date_to')
        if date_from and date_to:
            return fields.Date.to_date(date_from), fields.Date.to_date(date_to)
        date_range = self.env['sn.wsd.stock.balance.range']._current(self.env)
        return date_range.date_from, date_range.date_to

    def action_open_details(self):
        """下钻：打开本行（物料 × 仓库）在报表区间内的收发流水明细。"""
        self.ensure_one()
        date_from, date_to = self._report_period()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'sn_wsd_stock_report.action_sn_wsd_stock_balance_detail'
        )
        domain = [
            ('product_id', '=', self.product_id.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ]
        if self.warehouse_id:
            domain.append(('warehouse_id', '=', self.warehouse_id.id))
        action.update({
            'name': self.env._(
                '收发明细：%s（%s ~ %s）',
                self.product_id.display_name, date_from, date_to,
            ),
            'domain': domain,
        })
        return action
