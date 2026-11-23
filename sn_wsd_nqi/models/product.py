from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nqi_product_kind = fields.Selection(
        [('board', 'PCB Board'), ('machine', 'Complete Meter')],
        string='NQI Product Kind', index=True,
        help='Board vs complete-meter axis for NQI generation routing: '
             'plan detail TYPE (01 meter / 02 PCB) and which process '
             'table a station-pass row lands in. Explicit configuration, '
             'no workshop-based inference.')


class ProductProduct(models.Model):
    _inherit = 'product.product'

    nqi_product_kind = fields.Selection(
        related='product_tmpl_id.nqi_product_kind',
        string='NQI Product Kind')

    def _nqi_product_kind(self):
        """Routing key for the generation layer ('board'/'machine'/False)."""
        self.ensure_one()
        return self.nqi_product_kind or False
