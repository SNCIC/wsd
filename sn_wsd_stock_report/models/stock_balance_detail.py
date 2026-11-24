from odoo import fields, models
from odoo.tools import drop_view_if_exists

# stock_move_line.date 存的是 UTC naive 时间戳，期间归属必须换算到业务时区，
# 否则每天 0:00-8:00 的流水会被算到前一天（进而落到区间外）。
BUSINESS_TIMEZONE = 'Asia/Shanghai'


class SnWsdStockBalanceDetail(models.Model):
    """收发汇总表的下钻明细（库存收发流水）。

    汇总表 ``sn.wsd.stock.balance.report`` 直接以本视图为数据源聚合，口径只有
    这一份，所以「明细按方向相加」必然等于汇总行的期初/收入/发出/结存。

    口径与汇总一致：

    * 行粒度是「库存流水 × 报表库位」，因为一笔跨库位的调拨在两端各算一条。
      报表库位由 ``stock.location.sn_report_location_id`` 给出：现场把真正的仓
      （原材料仓、成品仓、线边仓……）建成库位，其下的货位/按灯货架归集到所属
      的仓，所以货位之间的移动不会进报表，只有「仓与仓（或仓库与外部）之间」
      的移动才算收发。
    * 收入 = 目标库位在某个报表库位内、来源库位不在同一报表库位的流水；
      发出 = 来源库位在某个报表库位内、目标库位不在同一报表库位的流水。
    * 同一报表库位内部的调拨（含其下货位之间）不出现。
    """

    _name = 'sn.wsd.stock.balance.detail'
    _description = 'Stock In/Out Balance Report Detail'
    _auto = False
    _rec_name = 'default_code'
    _order = 'date desc, id desc'

    warehouse_id = fields.Many2one('stock.warehouse', string='仓库', readonly=True)
    report_location_id = fields.Many2one(
        'stock.location', string='库位', readonly=True,
    )
    product_id = fields.Many2one('product.product', string='物料', readonly=True)
    default_code = fields.Char(string='物料编码', readonly=True)
    product_name = fields.Char(string='物料名称', readonly=True)
    material_specification = fields.Char(string='规格型号', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='单位', readonly=True)
    move_line_id = fields.Many2one('stock.move.line', string='库存流水', readonly=True)
    direction = fields.Selection(
        [('in', '收入'), ('out', '发出')], string='方向', readonly=True,
    )
    date = fields.Date(string='日期', readonly=True)
    reference = fields.Char(string='单据', readonly=True)
    picking_id = fields.Many2one('stock.picking', string='调拨单', readonly=True)
    partner_id = fields.Many2one('res.partner', string='往来单位', readonly=True)
    location_id = fields.Many2one('stock.location', string='来源库位', readonly=True)
    location_dest_id = fields.Many2one('stock.location', string='目标库位', readonly=True)
    lot_id = fields.Many2one('stock.lot', string='批次/序列号', readonly=True)
    quantity = fields.Float(string='数量', digits='Product Unit', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH flow AS (
                    -- 只看跨报表库位的已完成流水：两端报表库位相同（含其下货位之间）
                    -- 属于库内移动，不算收也不算发。
                    SELECT line.id AS move_line_id,
                           line.product_id,
                           line.quantity,
                           line.lot_id,
                           line.picking_id,
                           line.location_id,
                           line.location_dest_id,
                           source.sn_report_location_id AS source_report_location_id,
                           destination.sn_report_location_id AS destination_report_location_id,
                           (line.date AT TIME ZONE 'UTC' AT TIME ZONE '{BUSINESS_TIMEZONE}')::date AS local_date,
                           move.reference,
                           move.partner_id
                    FROM stock_move_line line
                    LEFT JOIN stock_location source ON source.id = line.location_id
                    LEFT JOIN stock_location destination ON destination.id = line.location_dest_id
                    -- move_id 理论上有值，但这里用 LEFT JOIN，保证不会因为缺单据而少统计一条流水
                    LEFT JOIN stock_move move ON move.id = line.move_id
                    WHERE line.state = 'done'
                      AND (source.sn_report_location_id IS NOT NULL
                           OR destination.sn_report_location_id IS NOT NULL)
                      AND source.sn_report_location_id IS DISTINCT FROM destination.sn_report_location_id
                ),
                leg AS (
                    -- 一笔流水在目标库位构成收入，在来源库位构成发出
                    SELECT flow.*, flow.destination_report_location_id AS report_location_id, 'in' AS direction
                    FROM flow
                    WHERE flow.destination_report_location_id IS NOT NULL

                    UNION ALL

                    SELECT flow.*, flow.source_report_location_id, 'out'
                    FROM flow
                    WHERE flow.source_report_location_id IS NOT NULL
                )
                SELECT
                       -- 行 id 由流水 id 与方向编出：一笔流水最多一收一付，所以不会撞号，
                       -- 且流水只增不减（已完成的流水不会被删），id 也就不会随行数漂移——
                       -- 点行打开单据时不会拿到别的流水。库存流水 id < 1073741823 即可。
                       leg.move_line_id * 2 + CASE leg.direction WHEN 'out' THEN 1 ELSE 0 END AS id,
                       report_location.warehouse_id,
                       leg.report_location_id,
                       leg.product_id,
                       product.default_code,
                       COALESCE(template.name->>'zh_CN', template.name->>'en_US') AS product_name,
                       template.material_specification,
                       template.uom_id,
                       leg.move_line_id,
                       leg.direction,
                       leg.local_date AS date,
                       leg.reference,
                       leg.picking_id,
                       leg.partner_id,
                       leg.location_id,
                       leg.location_dest_id,
                       leg.lot_id,
                       leg.quantity
                FROM leg
                JOIN stock_location report_location ON report_location.id = leg.report_location_id
                JOIN product_product product ON product.id = leg.product_id
                JOIN product_template template ON template.id = product.product_tmpl_id
            )
        """)

    def action_open_document(self):
        """下钻到来源单据：优先打开调拨单，没有单据（如库存调整）时打开库存流水本身。"""
        self.ensure_one()
        if self.picking_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'res_id': self.picking_id.id,
                'view_mode': 'form',
                'views': [[False, 'form']],
            }
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move.line',
            'res_id': self.move_line_id.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
        }
