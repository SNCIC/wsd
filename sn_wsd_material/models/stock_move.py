from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    material_specification = fields.Char(
        related='product_id.material_specification',
        string='Material Specification',
        readonly=True,
    )


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    material_specification = fields.Char(
        related='product_id.material_specification',
        string='Material Specification',
        readonly=True,
    )
