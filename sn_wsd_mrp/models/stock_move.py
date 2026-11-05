from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_mo_total_consumed_qty = fields.Float(
        string='Total Consumed',
        compute='_compute_x_mo_total_consumed_qty',
        digits='Product Unit',
    )

    def _adjust_procure_method(self, picking_type_code=False):
        res = super()._adjust_procure_method(picking_type_code)
        # A workshop store component without any bill of materials has nothing
        # to manufacture: the store demand would find no replenishment rule and
        # confirming the order would fail. Keep it on "take from stock", which
        # is what used to happen before the store rules existed.
        for move in self:
            if not move.raw_material_production_id or move.procure_method != 'make_to_order':
                continue
            rule = move.rule_id
            if not rule or not rule.x_workshop_store_rule or rule.action != 'pull':
                continue
            boms = move.product_id.bom_ids.filtered(
                lambda bom: bom.active and bom.type == 'normal')
            if not boms:
                move.procure_method = 'make_to_stock'
                move.rule_id = False
        return res

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
