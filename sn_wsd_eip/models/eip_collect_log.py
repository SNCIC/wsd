"""Gateway fetch log: one row per /api/eip/collect/<code> call, success
or failure -- the joint-testing evidence and the first place to look
when the platform reports missing data."""
from odoo import fields, models


class EipCollectLog(models.Model):
    _name = 'sn.wsd.eip.collect.log'
    _description = 'EIP Collect Fetch Log'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    code = fields.Char(
        string='Info Type Code', required=True, index=True,
        help='Interface code of the fetch URL.')
    amount = fields.Integer(
        string='Requested Limit',
        help='amount the gateway asked for (0 = request rejected before '
             'the limit check).')
    returned = fields.Integer(
        string='Returned Rows',
        help='Data records actually returned to the gateway.')
    source = fields.Char(
        string='Source', help='Remote address of the gateway call.')
    state = fields.Selection(
        selection=[('success', 'Success'), ('error', 'Error')],
        string='State', required=True, default='success', index=True)
    error_message = fields.Text(string='Error Message')
