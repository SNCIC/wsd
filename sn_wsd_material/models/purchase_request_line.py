from odoo import fields, models


class PurchaseRequestLine(models.Model):
    _inherit = "purchase.request.line"

    material_specification = fields.Char(
        related="product_id.material_specification",
        string="Material Specification",
        readonly=True,
    )
