from odoo import fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    material_sn_base = fields.Char(
        string='Material SN Base',
        copy=False,
        index=True,
        readonly=True,
    )
    material_sn_suffix = fields.Char(
        string='Material SN Suffix',
        copy=False,
        readonly=True,
    )
    supplier_code = fields.Char(
        string='Supplier Code',
        copy=False,
        readonly=True,
    )
    supplier_name = fields.Char(
        string='Supplier Name',
        copy=False,
        readonly=True,
    )
    supplier_batch_no = fields.Char(
        string='Supplier Batch',
        copy=False,
        readonly=True,
    )
    initial_quantity = fields.Float(
        string='Initial Quantity',
        copy=False,
        readonly=True,
        digits='Product Unit',
    )
    source_picking_id = fields.Many2one(
        'stock.picking',
        string='Source Receipt',
        copy=False,
        readonly=True,
        index=True,
        check_company=True,
    )
    source_move_line_id = fields.Many2one(
        'stock.move.line',
        string='Source Operation Line',
        copy=False,
        readonly=True,
        index=True,
        check_company=True,
    )
    label_print_count = fields.Integer(
        string='Label Print Count',
        default=0,
        copy=False,
        readonly=True,
    )
