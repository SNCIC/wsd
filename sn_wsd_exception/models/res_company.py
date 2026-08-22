from odoo import fields, models


class Company(models.Model):
    _inherit = 'res.company'

    exception_supervisor_user_id = fields.Many2one(
        'res.users',
        string='Exception Escalation Supervisor',
        help='Notified at escalation stage 2 (after the line team leader).',
    )
    exception_manager_user_id = fields.Many2one(
        'res.users',
        string='Exception Escalation Manager',
        help='Notified at escalation stage 3 and above.',
    )
