from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SnWsdPieceRate(models.Model):
    _name = 'sn.wsd.piece.rate'
    _description = 'Piece Rate'
    _check_company_auto = True
    _order = 'operation_id, product_id, id'
    _rec_name = 'display_label'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        index=True,
        check_company=True,
        ondelete='restrict',
    )
    operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='Operation',
        required=True,
        index=True,
        check_company=True,
        ondelete='restrict',
    )
    price = fields.Float(
        string='Price per Unit',
        digits=(12, 5),
        required=True,
        help='Amount paid to the crew for one OK unit of this product at '
             'this operation. Settlements store a snapshot: later changes '
             'only affect newly created settlements.',
    )
    display_label = fields.Char(compute='_compute_display_label')

    _sn_wsd_piece_rate_uniq = models.Constraint(
        'unique(company_id, product_id, operation_id)',
        'A piece rate already exists for this product and operation.',
    )

    @api.constrains('price')
    def _check_price_positive(self):
        for rate in self:
            if rate.price <= 0.0:
                raise ValidationError(_(
                    'The piece rate price must be greater than zero.'))

    @api.depends('product_id.display_name', 'operation_id.display_name')
    def _compute_display_label(self):
        for rate in self:
            rate.display_label = ' / '.join(filter(None, [
                rate.product_id.display_name,
                rate.operation_id.display_name,
            ]))
