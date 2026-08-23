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
    smt_consumption_ids = fields.One2many(
        'sn.smt.material.consumption', 'material_lot_id', string='SMT Product Usage',
    )
    smt_consumption_count = fields.Integer(
        string='SMT Product Usage Count', compute='_compute_smt_consumption_count',
    )
    # 卷级点数账本：初始 − 累计扣点，跨制令单累计（理论口径，不含抛料）。
    x_smt_consumed_points = fields.Float(
        string='SMT Consumed Points',
        compute='_compute_x_smt_point_balance',
    )
    x_smt_point_balance = fields.Float(
        string='SMT Point Balance',
        compute='_compute_x_smt_point_balance',
    )

    @api.depends('quant_ids.quantity', 'quant_ids.location_id.usage')
    def _compute_x_smt_available_qty(self):
        for lot in self:
            lot.x_smt_available_qty = sum(
                lot.quant_ids.filtered(
                    lambda quant: quant.location_id.usage in ('internal', 'transit')
                ).mapped('quantity')
            )

    @api.depends('smt_consumption_ids.consumed_qty')
    def _compute_x_smt_point_balance(self):
        for lot in self:
            consumed = sum(lot.smt_consumption_ids.mapped('consumed_qty'))
            base = lot.x_smt_initial_qty or lot.product_qty
            lot.x_smt_consumed_points = consumed
            lot.x_smt_point_balance = max(base - consumed, 0.0)

    @api.depends('smt_consumption_ids')
    def _compute_smt_consumption_count(self):
        for lot in self:
            lot.smt_consumption_count = len(lot.smt_consumption_ids)

    def action_view_smt_consumption(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lot Product Usage',
            'res_model': 'sn.smt.material.consumption',
            'view_mode': 'list,form',
            'domain': [('material_lot_id', '=', self.id)],
            'context': {'default_material_lot_id': self.id},
        }
