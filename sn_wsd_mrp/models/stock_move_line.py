from odoo import api, models

# MES 领料域的作业类型序列码（issue=领料 / return=退料 / over=超领）
MES_PICKING_SEQUENCE_CODES = (
    'sn.wsd.mes.picking.issue',
    'sn.wsd.mes.picking.return',
    'sn.wsd.mes.picking.over',
)


class StockMoveLineIssueReel(models.Model):
    """领料调拨上的扫 SN 带量：给行挂/换物料SN时，数量自动取该卷在
    调拨源库位的当前余量（批次料剪不开，出入库口径=整卷余量）。

    作用域限定在 MES 领料三兄弟作业类型（领料/退料/超领，源库位随
    方向自然对调）；完工收货建新批次、倒冲等其他调拨不受影响；
    幂等（余量未变不重写）。"""
    _inherit = 'stock.move.line'

    def _issue_reel_sync_qty(self):
        for line in self:
            picking = line.picking_id or line.move_id.picking_id
            if not picking \
                    or picking.picking_type_id.sequence_code not in MES_PICKING_SEQUENCE_CODES:
                continue
            if line.product_id.tracking != 'lot' or not line.lot_id:
                continue
            groups = self.env['stock.quant']._read_group(
                [
                    ('product_id', '=', line.product_id.id),
                    ('lot_id', '=', line.lot_id.id),
                    ('location_id', '=', line.location_id.id),
                    ('quantity', '>', 0),
                ],
                groupby=[],
                aggregates=['quantity:sum'],
            )
            balance = (groups[0][0] or 0.0) if groups else 0.0
            if balance > 0 and abs(line.quantity - balance) > 0.0001:
                line.quantity = balance

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._issue_reel_sync_qty()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if vals.get('lot_id'):
            # 只同步本次被挂/换批次的行；写 quantity 不会再触发（lot_id 不在 vals）
            self.filtered(lambda l: l.lot_id and l.lot_id.id == vals['lot_id']) \
                ._issue_reel_sync_qty()
        return res
