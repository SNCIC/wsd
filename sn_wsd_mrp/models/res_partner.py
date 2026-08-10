from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_customer_alias = fields.Char(string='Customer Alias', index=True)
