from odoo import fields, models


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    material_specification = fields.Char(
        related='product_id.material_specification',
        string='Material Specification',
        readonly=True,
    )
