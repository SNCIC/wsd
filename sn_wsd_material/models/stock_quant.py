from odoo import fields, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    material_specification = fields.Char(
        related='product_id.material_specification',
        string='Material Specification',
        readonly=True,
    )
