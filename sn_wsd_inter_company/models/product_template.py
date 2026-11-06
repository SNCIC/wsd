from odoo import fields, models


class ProductTemplate(models.Model):
    """Mark the products the trade with another company brought into existence.

    The resolver of the product mapping creates a product in the buying company
    when the article it buys was never purchased before. The flag keeps those
    rows identifiable, so a later catalogue clean-up can tell them apart from
    the products entered by hand.
    """

    _inherit = 'product.template'

    intercompany_generated = fields.Boolean(
        string='Created by Inter-Company Trade',
        copy=False,
        readonly=True,
        index=True,
        help="Set when the product was created automatically to receive an "
             "article bought from another company of this database.")
