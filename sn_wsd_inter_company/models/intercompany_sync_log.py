from odoo import fields, models


class SnIntercompanySyncLog(models.Model):
    """One line per synchronization attempt, kept as the audit trail of the
    trade chain and as the source of the comparison snapshot."""

    _name = 'sn.intercompany.sync.log'
    _description = 'Inter-Company Synchronization Log'
    _order = 'id desc'

    agreement_id = fields.Many2one(
        'sn.intercompany.agreement', string='Agreement',
        ondelete='cascade', index=True)
    direction = fields.Selection(
        [('a_to_b', 'Company A to Company B'),
         ('b_to_a', 'Company B to Company A')],
        string='Direction',
    )
    action = fields.Selection(
        [('create', 'Create'),
         ('update', 'Update'),
         ('cancel', 'Cancel'),
         ('delete', 'Delete'),
         ('check', 'Consistency Check')],
        required=True,
    )
    result = fields.Selection(
        [('success', 'Success'), ('skipped', 'Skipped'), ('failed', 'Failed')],
        default='success',
        required=True,
    )
    source_model = fields.Char(string='Source Model', index=True)
    source_id = fields.Integer(string='Source Id')
    source_ref = fields.Char(string='Source Document')
    target_model = fields.Char(string='Target Model', index=True)
    target_id = fields.Integer(string='Target Id')
    target_ref = fields.Char(string='Target Document')
    root_ref = fields.Char(string='Trade Chain', index=True)
    detail = fields.Text()
    diff = fields.Json(string='Changes')
    snapshot = fields.Json(
        help="Values written on the target document, used to detect that the "
             "other company modified it meanwhile.")
    duration_ms = fields.Integer(string='Duration (ms)')
    user_id = fields.Many2one(
        'res.users', string='User', default=lambda self: self.env.uid)
