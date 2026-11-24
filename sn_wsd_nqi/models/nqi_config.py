from odoo import _, api, fields, models


class NqiConfig(models.Model):
    """Per-company NQI integration settings, maintained from a page.

    Single source for the enterprise code stamped on every mirror row
    (envelope default) and for the push API connection parameters. The
    API spec arrives later: filling this table plus implementing the
    transport adapter method is all that remains then -- mirror and
    generation layers stay untouched.
    """
    _name = 'sn.wsd.nqi.config'
    _description = 'NQI Integration Config'
    _check_company_auto = True

    name = fields.Char(
        string='Name', required=True, copy=True,
        default=lambda self: _('NQI Integration Config'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    enterprise_code = fields.Char(
        string='Enterprise Code', required=True,
        help='Our ENTERPRISE_CODE issued by the NQI platform.')
    api_base_url = fields.Char(
        string='API Base URL',
        help='Push API endpoint. May stay empty until the NQI side '
             'publishes the interface spec.')
    auth_type = fields.Selection(
        [('none', 'None'), ('bearer', 'Bearer Token'),
         ('api_key', 'API Key'), ('basic', 'Basic Auth')],
        string='Auth Type', default='bearer', required=True)
    api_token = fields.Char(
        string='API Token', copy=False,
        groups='sn_wsd_nqi.group_nqi_manager')
    timeout_sec = fields.Integer(
        string='Timeout (seconds)', default=30, required=True)
    retry_times = fields.Integer(
        string='Retry Times', default=3, required=True)
    active = fields.Boolean(
        string='Active', default=True,
        help='Disable instead of deleting: push logs must stay able to '
             'trace the config a batch was pushed under.')

    _company_uniq = models.Constraint(
        'unique(company_id)',
        'Only one NQI integration config per company.',
    )
