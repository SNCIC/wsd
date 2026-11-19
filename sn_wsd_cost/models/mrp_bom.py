from odoo import api, fields, models


class MrpBom(models.Model):
    """Cost summary of the bill of materials.

    The summary reads the stored cost of the components, so opening a BoM gives
    the material cost built on the latest purchase prices without running the
    whole BoM overview report.
    """

    _inherit = 'mrp.bom'

    sn_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='company_id.currency_id',
        readonly=True,
    )
    sn_material_cost = fields.Monetary(
        string='Material Cost',
        compute='_compute_sn_cost',
        currency_field='sn_currency_id',
        help='Cost of the components for one BoM cycle, at the latest purchase '
             'prices.',
    )
    sn_operation_cost = fields.Monetary(
        string='Operation Cost',
        compute='_compute_sn_cost',
        currency_field='sn_currency_id',
        help='Cost of the operations for one BoM cycle.',
    )
    sn_total_cost = fields.Monetary(
        string='Total Cost',
        compute='_compute_sn_cost',
        currency_field='sn_currency_id',
    )
    sn_unit_cost = fields.Monetary(
        string='Unit Cost',
        compute='_compute_sn_cost',
        currency_field='sn_currency_id',
        help='Total cost divided by the quantity the BoM produces.',
    )

    @api.depends(
        'bom_line_ids.sn_cost_amount',
        'operation_ids',
        'product_qty',
        'product_id',
        'product_tmpl_id',
    )
    def _compute_sn_cost(self):
        for bom in self:
            material = sum(bom.bom_line_ids.mapped('sn_cost_amount'))
            product = bom.product_id or bom.product_tmpl_id.product_variant_id
            operation = 0.0
            for routing in bom.operation_ids:
                operation += routing.with_context(
                    product=product, quantity=bom.product_qty).cost
            total = material + operation
            bom.sn_material_cost = material
            bom.sn_operation_cost = operation
            bom.sn_total_cost = total
            bom.sn_unit_cost = total / bom.product_qty if bom.product_qty else 0.0
