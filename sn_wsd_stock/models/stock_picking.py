from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    can_generate_reel_lots = fields.Boolean(compute='_compute_can_generate_reel_lots')
    reel_split_ids = fields.One2many('sn.lot.reel.split', 'picking_id', string='Reel Splits', readonly=True)
    reel_split_count = fields.Integer(compute='_compute_reel_split_count')

    @api.depends('state', 'picking_type_id', 'move_ids.product_id.tracking')
    def _compute_can_generate_reel_lots(self):
        store_type_ids = set(self.env['stock.warehouse'].search([
            ('reception_steps', 'in', ('two_steps', 'three_steps')),
            ('store_type_id', '!=', False),
        ]).store_type_id.ids)
        for picking in self:
            picking.can_generate_reel_lots = bool(
                picking.state not in ('draft', 'done', 'cancel')
                and picking.picking_type_id.id in store_type_ids
                and any(move.product_id.tracking == 'lot' for move in picking.move_ids)
            )

    @api.depends('reel_split_ids')
    def _compute_reel_split_count(self):
        for picking in self:
            picking.reel_split_count = len(picking.reel_split_ids)

    def action_open_reel_split_wizard(self):
        self.ensure_one()
        if not self.can_generate_reel_lots:
            raise UserError(_('Reel lots can only be generated on an active storage transfer for lot-tracked products.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Reel Lots'),
            'res_model': 'sn.lot.reel.split.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id},
        }

    def action_view_reel_splits(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('sn_wsd_stock.action_lot_reel_split')
        action['domain'] = [('picking_id', '=', self.id)]
        action['context'] = {'default_picking_id': self.id}
        return action
