from odoo import fields, models


class StockRule(models.Model):
    _inherit = 'stock.rule'

    x_workshop_store_rule = fields.Boolean(
        string='Workshop Store Rule',
        copy=False,
        help='Rule derived from the workshop store configuration. It keeps the '
             'sub-level BOM of a workshop manufacturing order manufactured when '
             'the store hangs outside the warehouse stock chain.',
    )
