from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    sn_is_toll_customer = fields.Boolean(
        string='Toll Manufacturing Customer',
        help='The partner entrusts us with material to process: the supplied '
             'material and the finished goods stay his property and are '
             'excluded from our stock valuation.',
    )
    sn_toll_order_ids = fields.One2many(
        'sn.toll.order', 'partner_id', string='Toll Manufacturing Orders',
        copy=False,
    )
    sn_toll_order_count = fields.Integer(
        string='Toll Order Count',
        compute='_compute_sn_toll_order_count',
    )

    @api.depends('sn_toll_order_ids')
    def _compute_sn_toll_order_count(self):
        for partner in self:
            partner.sn_toll_order_count = len(partner.sn_toll_order_ids)
