from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class EipConfig(models.Model):
    """Per-company EIP order-push integration settings.

    Single source of the supplier identity stamped on every pushed
    envelope and of the HTTP connection parameters shared by the pull
    and push engines. One row per company; later batches fetch it
    through ``_eip_config_for`` before any outbound call.
    """
    _name = 'sn.wsd.eip.config'
    _description = 'EIP Integration Config'
    _check_company_auto = True

    name = fields.Char(
        string='Name', required=True, copy=True,
        default=lambda self: _('EIP Integration Config'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    supplier_code = fields.Char(
        string='Supplier Code', required=True,
        help='Supplier code issued by the EIP platform.')
    supplier_name = fields.Char(
        string='Supplier Name', required=True)
    purchaser_hq_code = fields.Char(
        string='Purchaser HQ Code', required=True, default='SGCC',
        help='Purchaser headquarters code stamped on every envelope.')
    base_url = fields.Char(
        string='Base URL', required=True,
        help='Interface root address, e.g. https://host:port.')
    timeout_sec = fields.Integer(
        string='Timeout (seconds)', default=30, required=True)
    update_mode = fields.Selection(
        [('diff', 'Diff'), ('full', 'Full')],
        string='Update Mode', default='diff', required=True,
        help='Diff sends only changed fields on UPDATE; Full always '
             'sends the complete envelope.')
    push_batch_size = fields.Integer(
        string='Push Batch Size', default=50, required=True,
        help='Documents pushed in one queue run, per company.')
    retry_times = fields.Integer(
        string='Retry Times', default=3, required=True)
    retry_interval_min = fields.Integer(
        string='Retry Interval (minutes)', default=10, required=True)
    pull_page_size = fields.Integer(
        string='Pull Page Size', default=1000, required=True,
        help='pageSize sent to the purchase-order pull interface; '
             'capped at 1000.')
    pull_daily_limit = fields.Integer(
        string='Pull Daily Limit', default=100, required=True,
        help='Maximum purchase-order pull requests per Beijing day, '
             'manual and scheduled pulls alike; 0 = unlimited (e.g. on '
             'the test environment).')
    pull_overlap_hours = fields.Integer(
        string='Pull Overlap (hours)', default=24, required=True,
        help='Hours re-pulled before the watermark to catch late '
             'updates.')
    pull_start_date = fields.Date(
        string='Pull Start Date',
        help='First-sync start date; empty = no update-time condition.')
    default_category_id = fields.Many2one(
        'sn.wsd.eip.category', string='Default Category',
        help='Category code default on business forms.')
    default_subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='Default Subclass',
        help='Subclass code default on business forms.')
    active = fields.Boolean(
        string='Active', default=True,
        help='Disable instead of deleting: logs must stay able to '
             'trace the config a call was made under.')

    _company_uniq = models.Constraint(
        'unique(company_id)',
        'Only one EIP integration config per company.',
    )

    @api.constrains('pull_page_size')
    def _check_pull_page_size(self):
        for config in self:
            if config.pull_page_size < 1:
                raise ValidationError(_('Page size must be at least 1.'))
            if config.pull_page_size > 1000:
                raise ValidationError(_('Page size cannot exceed 1000.'))

    @api.model
    def _eip_config_for(self, company=None):
        """Return the active config of ``company`` (default: the
        current company). All later batches start from here."""
        company = company or self.env.company
        config = self.search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], limit=1)
        if not config:
            raise UserError(_(
                'No active EIP integration config for company "%s". '
                'Maintain it under EIP > Configuration first.',
                company.display_name))
        return config

    @api.model
    def _eip_default(self, field_name):
        """Value of ``field_name`` on the current company's active
        config (a default for the business forms), or False. Never
        raises: usable as a field default."""
        config = self.search([
            ('company_id', '=', self.env.company.id),
            ('active', '=', True)], limit=1)
        return config[field_name] if config else False
