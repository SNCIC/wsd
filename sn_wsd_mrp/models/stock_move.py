from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_mo_total_consumed_qty = fields.Float(
        string='Total Consumed',
        compute='_compute_x_mo_total_consumed_qty',
        digits='Product Unit',
    )

    @api.depends(
        'quantity',
        'state',
        'raw_material_production_id.move_raw_ids.quantity',
        'raw_material_production_id.move_raw_ids.state',
        'raw_material_production_id.move_raw_ids.product_id',
        'raw_material_production_id.move_raw_ids.bom_line_id',
        'raw_material_production_id.move_raw_ids.operation_id',
    )
    def _compute_x_mo_total_consumed_qty(self):
        for move in self:
            production = move.raw_material_production_id
            if not production:
                move.x_mo_total_consumed_qty = move.quantity
                continue

            related_moves = production.move_raw_ids.filtered(
                lambda candidate:
                    candidate.product_id == move.product_id
                    and candidate.bom_line_id == move.bom_line_id
                    and candidate.operation_id == move.operation_id
                    and candidate.state != 'cancel'
            )
            move.x_mo_total_consumed_qty = sum(related_moves.mapped('quantity'))
