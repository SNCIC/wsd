from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_customer_alias = fields.Char(string='Customer Alias', index=True)
    manufacturer = fields.Char(
        string='Manufacturer',
        help='Maker of the material the partner supplies, when the goods '
             'come from a distributor rather than from the maker itself. '
             'Printed as "Manufacturer (Supplier)" on the incoming '
             'inspection record.',
    )
