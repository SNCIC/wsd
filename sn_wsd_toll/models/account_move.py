from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    sn_toll_order_id = fields.Many2one(
        'sn.toll.order', string='Toll Manufacturing Order', copy=False,
        index=True, check_company=True,
        help='Toll manufacturing order invoiced by this entry: processing '
             'fee or material loss claim.',
    )
