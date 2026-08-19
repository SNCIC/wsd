import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

TRIGGER_TIME_KEY = 'equipment_maintenance_trigger_time'
TIME_PATTERN = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')


class MaintenanceConfigWizard(models.TransientModel):
    """Settings dialog for the maintenance automation, independent of the
    spot check trigger time."""
    _name = 'sn.wsd.device.maint.config'
    _description = 'Maintenance Settings'

    trigger_time = fields.Char(
        string='Daily Trigger Time', required=True,
        help='Format HH:MM. Once this time is reached, the shared scheduled '
             'action generates the day\'s maintenance tasks for every due '
             'plan. Applies to all maintenance plans.')

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        defaults.setdefault(
            'trigger_time',
            self.env['ir.config_parameter'].sudo().get_param(
                TRIGGER_TIME_KEY, '08:30'))
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
        return {'type': 'ir.actions.act_window_close'}
