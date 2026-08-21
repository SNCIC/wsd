from odoo import fields, models


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    supplier_batch_no = fields.Char(
        string='Supplier Batch',
        copy=False,
        index=True,
    )
    material_sn_base = fields.Char(
        string='Material SN Base',
        copy=False,
        readonly=True,
        index=True,
    )
    material_sn_suffix = fields.Char(
        string='Material SN Suffix',
        copy=False,
        readonly=True,
    )
    material_label_printed = fields.Boolean(
        string='Material Label Printed',
        copy=False,
        readonly=True,
    )
