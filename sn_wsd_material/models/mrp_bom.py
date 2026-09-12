from odoo import fields, models


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    material_specification = fields.Char(
        related='product_tmpl_id.material_specification',
        string='Material Specification',
        readonly=True,
    )
