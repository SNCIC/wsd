from odoo import _, fields, models


class LotReelSplit(models.Model):
    _name = 'sn.lot.reel.split'
    _description = 'Lot Reel Split'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False, default='/')
    date = fields.Datetime(string='Split Date', required=True, readonly=True, default=fields.Datetime.now)
    picking_id = fields.Many2one(
        'stock.picking', string='Storage Transfer', required=True, readonly=True,
        check_company=True, ondelete='restrict', index=True,
    )
    source_move_id = fields.Many2one(
        'stock.move', string='Storage Move', required=True, readonly=True,
        check_company=True, ondelete='restrict', index=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Product', required=True, readonly=True,
        check_company=True, ondelete='restrict', index=True,
    )
    source_lot_id = fields.Many2one(
        'stock.lot', string='Source Lot', required=True, readonly=True,
        check_company=True, ondelete='restrict', index=True,
    )
    source_location_id = fields.Many2one(
        'stock.location', string='Source Location', required=True, readonly=True,
        check_company=True, ondelete='restrict',
    )
    quantity = fields.Float(string='Split Quantity', required=True, readonly=True, digits='Product Unit')
    product_uom_id = fields.Many2one('uom.uom', string='Unit', required=True, readonly=True)
    quantity_per_reel = fields.Float(string='Quantity per Reel', required=True, readonly=True, digits='Product Unit')
    line_ids = fields.One2many('sn.lot.reel.split.line', 'split_id', string='Reel Lots', readonly=True)
    conversion_move_ids = fields.One2many('stock.move', 'reel_split_id', string='Conversion Moves', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True, index=True)
    user_id = fields.Many2one('res.users', string='Split By', required=True, readonly=True, default=lambda self: self.env.user)

    _quantity_positive = models.Constraint(
        'CHECK(quantity > 0)',
        'The split quantity must be greater than zero.',
    )
    _quantity_per_reel_positive = models.Constraint(
        'CHECK(quantity_per_reel > 0)',
        'The quantity per reel must be greater than zero.',
    )

    def action_view_conversion_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Conversion Moves'),
            'res_model': 'stock.move',
            'view_mode': 'list,form',
            'domain': [('reel_split_id', '=', self.id)],
        }


class LotReelSplitLine(models.Model):
    _name = 'sn.lot.reel.split.line'
    _description = 'Lot Reel Split Line'
    _order = 'sequence, id'
    _check_company_auto = True

    split_id = fields.Many2one(
        'sn.lot.reel.split', string='Reel Split', required=True, readonly=True,
        ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Sequence', required=True, readonly=True)
    lot_id = fields.Many2one(
        'stock.lot', string='Reel Lot', required=True, readonly=True,
        check_company=True, ondelete='restrict', index=True,
    )
    quantity = fields.Float(string='Quantity', required=True, readonly=True, digits='Product Unit')
    location_dest_id = fields.Many2one(
        'stock.location', string='Destination Location', required=True, readonly=True,
        check_company=True, ondelete='restrict',
    )
    is_remainder = fields.Boolean(string='Remainder Reel', readonly=True)
    company_id = fields.Many2one(related='split_id.company_id', store=True, index=True)

    _quantity_positive = models.Constraint(
        'CHECK(quantity > 0)',
        'The reel quantity must be greater than zero.',
    )
    _split_sequence_unique = models.Constraint(
        'UNIQUE(split_id, sequence)',
        'The reel sequence must be unique within a split.',
    )
    _lot_unique = models.Constraint(
        'UNIQUE(lot_id)',
        'A reel lot can only belong to one split line.',
    )
