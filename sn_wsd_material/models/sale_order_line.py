from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    material_specification = fields.Char(
        related='product_id.material_specification',
        string='Material Specification',
        readonly=True,
    )
