from odoo import fields, models


class SnIntercompanyProductMap(models.Model):
    """Product of one company and the product standing for it in the other
    company.

    A product restricted to one company cannot be used on the documents of the
    other company, so the mapping is what lets a company sell the products it
    owns to its counterpart. A mapping without a target product means the
    source product is copied as a text line.
    """

    _name = 'sn.intercompany.product.map'
    _description = 'Inter-Company Product Mapping'
    _order = 'agreement_id, direction, id'

    agreement_id = fields.Many2one(
        'sn.intercompany.agreement', string='Agreement',
        required=True, ondelete='cascade', index=True)
    direction = fields.Selection(
        [('a_to_b', 'Company A to Company B'),
         ('b_to_a', 'Company B to Company A'),
         ('both', 'Both Directions')],
        default='both',
        required=True,
    )
    source_product_tmpl_id = fields.Many2one(
        'product.template', string='Source Product',
        required=True, ondelete='cascade')
    target_product_tmpl_id = fields.Many2one(
        'product.template', string='Target Product',
        ondelete='cascade',
        help="Product used on the documents of the other company. Leave empty "
             "to copy the source product as a text line.")
    uom_ratio = fields.Float(
        string='Unit Ratio', default=1.0,
        help="Quantity of the source line is multiplied by this ratio before "
             "it is written on the target line.")
    price_factor = fields.Float(
        string='Price Factor', default=1.0,
        help="Unit price of the source line is multiplied by this factor.")
    active = fields.Boolean(default=True)
    note = fields.Char()

    _product_map_uniq = models.Constraint(
        'UNIQUE(agreement_id, direction, source_product_tmpl_id)',
        'A product mapping already exists for this agreement and direction.',
    )

    def _mapped_product(self):
        self.ensure_one()
        if not self.target_product_tmpl_id:
            return self.env['product.product']
        return self.target_product_tmpl_id.product_variant_id
