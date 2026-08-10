from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SnWsdExceptionType(models.Model):
    _name = 'sn.wsd.exception.type'
    _description = 'SN WSD Exception Type'
    _order = 'sequence, code, id'
    _check_company_auto = True

    name = fields.Char(string='Exception Type', required=True, translate=True)
    code = fields.Char(string='Type Code', required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    category = fields.Selection(
        [
            ('equipment', 'Equipment Failure'),
            ('quality', 'Quality Exception'),
            ('material', 'Material Exception'),
            ('personnel', 'Personnel Exception'),
            ('other', 'Other'),
        ],
        string='Category',
        required=True,
        default='other',
        index=True,
    )
    timeout_minutes = fields.Integer(
        string='Escalation Timeout Minutes',
        default=120,
        help='Open exceptions exceeding this age are escalated by the scheduled action.',
    )
    suspend_after_escalation_minutes = fields.Integer(
        string='Suspend After Escalation Minutes',
        default=120,
        help='Escalated exceptions exceeding this additional age are suspended by the scheduled action.',
    )
    notify_group_ids = fields.Many2many(
        'res.groups',
        'sn_wsd_exception_type_notify_group_rel',
        'type_id',
        'group_id',
        string='Notification Groups',
        help='Users in these groups receive an activity when this exception type is registered.',
    )
    escalation_group_ids = fields.Many2many(
        'res.groups',
        'sn_wsd_exception_type_escalation_group_rel',
        'type_id',
        'group_id',
        string='Escalation Groups',
        help='Users in these groups receive an activity when this exception type is escalated.',
    )
    description = fields.Text(string='Description')

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The exception type code must be unique per company.',
    )

    @api.constrains('timeout_minutes', 'suspend_after_escalation_minutes')
    def _check_timeout_minutes(self):
        for record in self:
            if record.timeout_minutes < 0:
                raise ValidationError('The escalation timeout must not be negative.')
            if record.suspend_after_escalation_minutes < 0:
                raise ValidationError('The suspension timeout must not be negative.')
