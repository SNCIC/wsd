from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SnIntercompanySyncIssue(models.Model):
    """A synchronization that could not be completed and needs a decision.

    Hard failures abort the transaction of the source document, so they never
    reach this queue. What lands here is what cannot be replayed blindly:
    documents that diverged, counterpart documents missing, and counterpart
    documents still open after the source was cancelled.
    """

    _name = 'sn.intercompany.sync.issue'
    _description = 'Inter-Company Synchronization Issue'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    state = fields.Selection(
        [('open', 'To Handle'), ('resolved', 'Resolved'), ('ignored', 'Ignored')],
        default='open',
        required=True,
        tracking=True,
    )
    issue_type = fields.Selection(
        [('config', 'Configuration'),
         ('data', 'Invalid Data'),
         ('state', 'Document State'),
         ('conflict', 'Conflicting Changes'),
         ('diverged', 'Diverged Documents'),
         ('missing', 'Missing Counterpart'),
         ('system', 'System Error')],
        string='Issue Type',
        required=True,
        tracking=True,
    )
    agreement_id = fields.Many2one(
        'sn.intercompany.agreement', string='Agreement',
        ondelete='cascade', index=True)
    direction = fields.Selection(
        [('a_to_b', 'Company A to Company B'),
         ('b_to_a', 'Company B to Company A')],
        string='Direction',
    )
    source_model = fields.Char(string='Source Model', index=True)
    source_id = fields.Integer(string='Source Id')
    source_ref = fields.Char(string='Source Document')
    target_model = fields.Char(string='Target Model', index=True)
    target_id = fields.Integer(string='Target Id')
    target_ref = fields.Char(string='Target Document')
    message = fields.Text(string='Reason')
    retry_count = fields.Integer(default=0, readonly=True)
    last_retry = fields.Datetime(readonly=True)
    resolved_user_id = fields.Many2one('res.users', string='Handled By', readonly=True)
    resolved_date = fields.Datetime(string='Handled On', readonly=True)
    note = fields.Text(string='Resolution Note')

    @api.depends('source_model', 'source_ref', 'target_ref')
    def _compute_name(self):
        for issue in self:
            issue.name = '%s -> %s' % (
                issue.source_ref or issue.source_model or _('Unknown'),
                issue.target_ref or _('Missing'),
            )

    def _get_source(self):
        self.ensure_one()
        if not self.source_model or not self.source_id:
            return self.env['sn.intercompany.sync.issue']
        return self.env[self.source_model].sudo().browse(self.source_id).exists()

    def _get_target(self):
        self.ensure_one()
        if not self.target_model or not self.target_id:
            return self.env['sn.intercompany.sync.issue']
        return self.env[self.target_model].sudo().browse(self.target_id).exists()

    def action_retry(self):
        for issue in self:
            source = issue._get_source()
            if not source:
                raise UserError(_(
                    "The source document of %(issue)s no longer exists.",
                    issue=issue.display_name))
            if issue.state != 'open':
                continue
            source._sn_replay_sync()
            issue.write({
                'state': 'resolved',
                'retry_count': issue.retry_count + 1,
                'last_retry': fields.Datetime.now(),
                'resolved_user_id': self.env.uid,
                'resolved_date': fields.Datetime.now(),
                'note': _('Replayed by %(user)s.', user=self.env.user.display_name),
            })

    def action_ignore(self):
        self.write({
            'state': 'ignored',
            'resolved_user_id': self.env.uid,
            'resolved_date': fields.Datetime.now(),
        })

    def action_resolve(self):
        self.write({
            'state': 'resolved',
            'resolved_user_id': self.env.uid,
            'resolved_date': fields.Datetime.now(),
        })

    def action_open_source(self):
        self.ensure_one()
        return self._document_action(self.source_model, self.source_id)

    def action_open_target(self):
        self.ensure_one()
        return self._document_action(self.target_model, self.target_id)

    @api.model
    def _document_action(self, model_name, record_id):
        if not model_name or not record_id:
            raise UserError(_("This issue has no document to open."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': model_name,
            'res_id': record_id,
            'view_mode': 'form',
            'target': 'current',
        }
