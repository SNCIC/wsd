from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    picklight_enabled = fields.Boolean(
        string='Enable Picklight',
        help='Allow outbound transfers to use picklight.')
