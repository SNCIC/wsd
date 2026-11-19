from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    sn_toll_partner_id = fields.Many2one(
        'res.partner', string='Toll Goods Owner',
        compute='_compute_sn_toll_partner_id',
        help='Customer owning the goods moved by the toll manufacturing '
             'chain. The reservation is restricted to that owner and the '
             'valuation excludes the move lines carrying it.',
    )

    @api.depends(
        'picking_id.sn_toll_order_id',
        'picking_id.owner_id',
        'picking_id.x_mes_order_id',
        'raw_material_production_id.sn_toll_partner_id',
        'production_id.sn_toll_partner_id',
    )
    def _compute_sn_toll_partner_id(self):
        for move in self:
            partner = self.env['res.partner']
            if move.raw_material_production_id:
                partner = move.raw_material_production_id.sn_toll_partner_id
            if not partner and move.production_id:
                partner = move.production_id.sn_toll_partner_id
            picking = move.picking_id
            if not partner and picking:
                if picking.sn_toll_order_id:
                    partner = picking.sn_toll_order_id.partner_id
                else:
                    partner = picking.owner_id
                if not partner and picking.x_mes_order_id:
                    partner = (
                        picking.x_mes_order_id.production_id.sn_toll_partner_id)
            move.sn_toll_partner_id = partner

    def _update_reserved_quantity_vals(self, need, location_id, lot_id=None,
                                       package_id=None, owner_id=None,
                                       strict=True):
        # Toll goods are only reserved for the transfer that processes them:
        # the owner of the goods is the customer, never the company.
        if not owner_id:
            owner_id = self.sn_toll_partner_id
        return super()._update_reserved_quantity_vals(
            need, location_id, lot_id, package_id, owner_id, strict)

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        vals = super()._prepare_move_line_vals(
            quantity=quantity, reserved_quant=reserved_quant)
        owner = self.sn_toll_partner_id
        if owner and not vals.get('owner_id'):
            vals['owner_id'] = owner.id
        return vals

    def _action_assign(self, force_qty=False):
        # The owner restriction drives both the reservation and the valuation
        # exclusion: set it before the standard assignment runs.
        for move in self:
            owner = move.sn_toll_partner_id
            if owner and not move.restrict_partner_id:
                move.restrict_partner_id = owner
        return super()._action_assign(force_qty=force_qty)

    def _action_done(self, cancel_backorder=False):
        for move in self:
            owner = move.sn_toll_partner_id
            if owner and not move.restrict_partner_id:
                move.restrict_partner_id = owner
        return super()._action_done(cancel_backorder=cancel_backorder)
