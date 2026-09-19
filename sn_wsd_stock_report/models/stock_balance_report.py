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
                warehouse_root AS (
                    -- 仓库库存区的根库位（WH/库存），不写死 id，换库/加仓都适用
                    SELECT warehouse.id AS warehouse_id,
                           location.parent_path AS root_path
                    FROM stock_warehouse warehouse
                    JOIN stock_location location ON location.id = warehouse.lot_stock_id
                ),
                scope AS (
                    -- 库存区内的全部库位；同一库位只归属一个仓库，避免流水被展开成多行
                    SELECT pair.location_id, min(pair.warehouse_id) AS warehouse_id
                    FROM (
                        SELECT root.warehouse_id, child.id AS location_id
                        FROM warehouse_root root
                        JOIN stock_location child
                          ON child.parent_path LIKE root.root_path || '%'
                    ) pair
                    GROUP BY pair.location_id
                ),
                flow AS (
                    -- 只看跨越库存区边界、且两端不同仓库的已完成流水
                    SELECT line.product_id,
                           line.quantity,
                           (line.date AT TIME ZONE 'UTC' AT TIME ZONE '{BUSINESS_TIMEZONE}') AS local_date,
                           source.warehouse_id AS source_warehouse_id,
                           destination.warehouse_id AS destination_warehouse_id
                    FROM stock_move_line line
                    LEFT JOIN scope source ON source.location_id = line.location_id
                    LEFT JOIN scope destination ON destination.location_id = line.location_dest_id
                    WHERE line.state = 'done'
                      AND (source.warehouse_id IS NOT NULL OR destination.warehouse_id IS NOT NULL)
                      AND source.warehouse_id IS DISTINCT FROM destination.warehouse_id
                ),
                leg AS (
                    -- 一笔流水在目标仓库构成收入，在来源仓库构成发出
                    SELECT flow.product_id,
                           flow.destination_warehouse_id AS warehouse_id,
                           flow.local_date,
                           flow.quantity AS qty_in,
                           0::numeric AS qty_out
                    FROM flow
                    WHERE flow.destination_warehouse_id IS NOT NULL

                    UNION ALL

                    SELECT flow.product_id,
                           flow.source_warehouse_id,
                           flow.local_date,
                           0::numeric,
                           flow.quantity
                    FROM flow
                    WHERE flow.source_warehouse_id IS NOT NULL
                ),
                summary AS (
                    SELECT leg.product_id,
                           leg.warehouse_id,
                           sum(CASE WHEN leg.local_date < param.date_from::timestamp
                                    THEN leg.qty_in - leg.qty_out ELSE 0 END) AS qty_initial,
                           sum(CASE WHEN leg.local_date >= param.date_from::timestamp
                                     AND leg.local_date < param.date_to::timestamp + interval '1 day'
                                    THEN leg.qty_in ELSE 0 END) AS qty_in,
                           sum(CASE WHEN leg.local_date >= param.date_from::timestamp
                                     AND leg.local_date < param.date_to::timestamp + interval '1 day'
                                    THEN leg.qty_out ELSE 0 END) AS qty_out
                    FROM leg
                    CROSS JOIN param
                    GROUP BY leg.product_id, leg.warehouse_id, param.date_from, param.date_to
                )
                SELECT row_number() OVER (
                           ORDER BY product.default_code, summary.warehouse_id
                       ) AS id,
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
