from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    exception_escalation_enabled = fields.Boolean(
        string='Enable Exception Auto-Escalation',
        config_parameter='sn_wsd_exception.escalation_enabled',
        default=False,
    )
    exception_respond_normal_minutes = fields.Integer(
        string='Normal: Response Limit (minutes)',
        config_parameter='sn_wsd_exception.respond_normal',
        default=30,
    )
    exception_respond_urgent_minutes = fields.Integer(
        string='Urgent: Response Limit (minutes)',
        config_parameter='sn_wsd_exception.respond_urgent',
        default=10,
    )
    exception_respond_critical_minutes = fields.Integer(
        string='Critical: Response Limit (minutes)',
        config_parameter='sn_wsd_exception.respond_critical',
        default=3,
    )
    exception_resolve_normal_minutes = fields.Integer(
        string='Normal: Resolution Limit (minutes)',
        config_parameter='sn_wsd_exception.resolve_normal',
        default=240,
    )
    exception_resolve_urgent_minutes = fields.Integer(
        string='Urgent: Resolution Limit (minutes)',
        config_parameter='sn_wsd_exception.resolve_urgent',
        default=60,
    )
    exception_resolve_critical_minutes = fields.Integer(
        string='Critical: Resolution Limit (minutes)',
        config_parameter='sn_wsd_exception.resolve_critical',
        default=30,
    )
    exception_level_normal_need_confirm = fields.Boolean(
        string='Normal: Closure Confirmation',
        config_parameter='sn_wsd_exception.level_normal_need_confirm',
        default=False,
    )
    exception_level_urgent_need_confirm = fields.Boolean(
        string='Urgent: Closure Confirmation',
        config_parameter='sn_wsd_exception.level_urgent_need_confirm',
        default=True,
    )
    exception_level_critical_need_confirm = fields.Boolean(
        string='Critical: Closure Confirmation',
        config_parameter='sn_wsd_exception.level_critical_need_confirm',
        default=True,
    )
    exception_supervisor_user_id = fields.Many2one(
        related='company_id.exception_supervisor_user_id',
        string='Escalation Supervisor',
        readonly=False,
    )
    exception_manager_user_id = fields.Many2one(
        related='company_id.exception_manager_user_id',
        string='Escalation Manager',
        readonly=False,
    )
