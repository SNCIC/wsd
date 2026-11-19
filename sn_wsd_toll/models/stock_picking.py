from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    sn_toll_order_id = fields.Many2one(
        'sn.toll.order', string='Toll Manufacturing Order', copy=False,
        index=True, check_company=True,
    )
    sn_toll_receipt = fields.Boolean(
        string='Toll Material Receipt', copy=False, index=True,
        help='The transfer receives the material supplied by the customer '
             'for a toll manufacturing order.',
    )
    sn_toll_delivery = fields.Boolean(
        string='Toll Finished Goods Delivery', copy=False, index=True,
        help='The transfer gives the finished goods back to the customer who '
             'owns them.',
    )
    sn_is_toll = fields.Boolean(
        string='Toll Manufacturing', compute='_compute_sn_is_toll',
        store=True, index=True,
    )

    @api.depends('sn_toll_order_id', 'sn_toll_receipt', 'sn_toll_delivery')
    def _compute_sn_is_toll(self):
        for picking in self:
            picking.sn_is_toll = bool(
                picking.sn_toll_order_id
                or picking.sn_toll_receipt
                or picking.sn_toll_delivery)

    def _action_done(self):
        # The owner set on the transfer is the customer owning the goods. The
        # standard validation writes it on the move lines and the moves, so
        # the valuation excludes them; the explicit write keeps the chain
        # consistent when a transfer was created without the owner field.
        for picking in self:
            if picking.sn_toll_order_id and picking.sn_toll_order_id.partner_id:
                partner = picking.sn_toll_order_id.partner_id
                if picking.owner_id != partner:
                    picking.owner_id = partner
        return super()._action_done()
