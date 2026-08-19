import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

TRIGGER_TIME_KEY = 'equipment_cal_trigger_time'
TIME_PATTERN = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')


class CalibrationConfigWizard(models.TransientModel):
    """Settings dialog for the calibration automation."""
    _name = 'sn.wsd.device.cal.config'
    _description = 'Calibration Settings'

    trigger_time = fields.Char(
        string='Daily Trigger Time', required=True,
        help='Format HH:MM. Once this time is reached, the shared scheduled '
             'action scans the calibration plans and generates the due '
             'tasks.')

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        defaults.setdefault(
            'trigger_time',
            self.env['ir.config_parameter'].sudo().get_param(
                TRIGGER_TIME_KEY, '08:00'))
        return defaults

    @api.constrains('trigger_time')
    def _check_trigger_time(self):
        for wizard in self:
            if not TIME_PATTERN.match(wizard.trigger_time.strip()):
                raise ValidationError(_(
                    'Invalid time format: %s. Expected HH:MM (00:00-23:59).',
                    wizard.trigger_time))

    def action_save(self):
        self.ensure_one()
        self.env['ir.config_parameter'].sudo().set_param(
            TRIGGER_TIME_KEY, self.trigger_time.strip())
        # Effective immediately: run the generation once so a trigger time
        # that already passed today applies right away instead of waiting
        # for the next cron wake-up (idempotent per plan and date).
        self.env['sn.wsd.device.cal.plan']._cron_generate_calibration_tasks()
        return {'type': 'ir.actions.act_window_close'}
