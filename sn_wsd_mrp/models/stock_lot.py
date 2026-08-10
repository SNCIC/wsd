from odoo import fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    x_panel_no = fields.Char(string='Panel No', index=True, copy=False)
    x_serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity',
        string='Physical Serial Identity',
        index=True,
        check_company=True,
        copy=False,
    )

