from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    # 单账本：卷（物料SN）的剩余以 stock.quant 在手为唯一真相，卷上不再
    # 维护点数账本；批次/供应商/初始数量由来料标签模块在收货时建档。
    x_smt_available_qty = fields.Float(
        string='Available Reel Qty',
        compute='_compute_x_smt_available_qty',
    )
    smt_consumption_ids = fields.One2many(
        'sn.smt.material.consumption', 'material_lot_id', string='SMT Product Usage',
    )
    smt_consumption_count = fields.Integer(
        string='SMT Product Usage Count', compute='_compute_smt_consumption_count',
    )

    @api.depends('quant_ids.quantity', 'quant_ids.location_id.usage')
    def _compute_x_smt_available_qty(self):
        for lot in self:
            lot.x_smt_available_qty = sum(
                lot.quant_ids.filtered(
                    lambda quant: quant.location_id.usage in ('internal', 'transit')
                ).mapped('quantity')
            )

    def _smt_on_hand_qty(self):
        """单卷在手数量（内部库位 + 调拨在途，SQL 聚合）——上料/转机取数
        与耗尽拒载的唯一来源。"""
        self.ensure_one()
        groups = self.env['stock.quant']._read_group(
            [
                ('lot_id', '=', self.id),
                ('location_id.usage', 'in', ('internal', 'transit')),
            ],
            groupby=['lot_id'],
            aggregates=['quantity:sum'],
        )
        return (groups[0][1] or 0.0) if groups else 0.0

    @api.depends('smt_consumption_ids')
    def _compute_smt_consumption_count(self):
        for lot in self:
            lot.smt_consumption_count = len(lot.smt_consumption_ids)

    def action_view_smt_consumption(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lot Product Usage',
            'res_model': 'sn.smt.material.consumption',
            'view_mode': 'list,form',
            'domain': [('material_lot_id', '=', self.id)],
            'context': {'default_material_lot_id': self.id},
        }
