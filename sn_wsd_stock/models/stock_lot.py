from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StockLot(models.Model):
    _inherit = 'stock.lot'

    parent_lot_id = fields.Many2one(
        'stock.lot',
        string='Source Lot',
        copy=False,
        index=True,
        check_company=True,
        domain="[('product_id', '=', product_id), ('id', '!=', id)]",
        help='Supplier or source lot from which this reel lot was generated.',
    )
    child_lot_ids = fields.One2many(
        'stock.lot',
        'parent_lot_id',
        string='Reel Lots',
        readonly=True,
    )
    child_lot_count = fields.Integer(compute='_compute_child_lot_count')
    reel_sequence = fields.Integer(string='Reel Sequence', copy=False, readonly=True)
    is_reel_lot = fields.Boolean(string='Reel Lot', copy=False, readonly=True, index=True)
    reel_split_line_id = fields.Many2one(
        'sn.lot.reel.split.line',
        string='Reel Split Line',
        copy=False,
        readonly=True,
        index=True,
        ondelete='restrict',
    )

    @api.depends('child_lot_ids')
    def _compute_child_lot_count(self):
        for lot in self:
            lot.child_lot_count = len(lot.child_lot_ids)

    @api.constrains('parent_lot_id', 'product_id', 'company_id')
    def _check_parent_lot(self):
        for lot in self.filtered('parent_lot_id'):
            if lot.parent_lot_id == lot:
                raise ValidationError(_('A lot cannot be its own source lot.'))
            if lot.parent_lot_id.product_id != lot.product_id:
                raise ValidationError(_('A reel lot and its source lot must use the same product.'))
            if lot.parent_lot_id.company_id and lot.company_id != lot.parent_lot_id.company_id:
                raise ValidationError(_('A reel lot and its source lot must belong to the same company.'))

    def action_view_reel_lots(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('stock.action_production_lot_form')
        action['domain'] = [('parent_lot_id', '=', self.id)]
        action['context'] = {
            'default_product_id': self.product_id.id,
            'default_parent_lot_id': self.id,
        }
        return action

    def action_view_source_lot(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Source Lot'),
            'res_model': 'stock.lot',
            'view_mode': 'form',
            'res_id': self.parent_lot_id.id,
        }
