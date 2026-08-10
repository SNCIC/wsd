from odoo import api, fields, models


REEL_STATE_SELECTION = [
    ('in_stock', 'In Stock'),
    ('prepared', 'Prepared'),
    ('loaded', 'Loaded'),
    ('unloaded', 'Unloaded'),
    ('depleted', 'Depleted'),
    ('scrapped', 'Scrapped'),
]


class StockLot(models.Model):
    _inherit = 'stock.lot'

    x_smt_offline_material_ids = fields.One2many(
        'sn.smt.offline.material',
        'material_lot_id',
        string='SMT Offline Preparation Records',
    )
    x_smt_is_reel = fields.Boolean(string='SMT Reel', copy=False)
    x_smt_supplier_lot_no = fields.Char(string='Supplier Lot No', copy=False)
    x_smt_date_code = fields.Char(string='Date Code', copy=False)
    x_smt_initial_qty = fields.Float(string='Initial Reel Qty', copy=False)
    x_smt_available_qty = fields.Float(
        string='Available Reel Qty',
        compute='_compute_x_smt_available_qty',
    )
    x_smt_reel_state = fields.Selection(
        REEL_STATE_SELECTION,
        string='SMT Reel State',
        default='in_stock',
        copy=False,
    )

    @api.depends('quant_ids.quantity', 'quant_ids.location_id.usage')
    def _compute_x_smt_available_qty(self):
        for lot in self:
            lot.x_smt_available_qty = sum(
                lot.quant_ids.filtered(
                    lambda quant: quant.location_id.usage in ('internal', 'transit')
                ).mapped('quantity')
            )
