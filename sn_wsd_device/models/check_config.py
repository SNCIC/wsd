import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

TRIGGER_TIME_KEY = 'equipment_inspection_trigger_time'
TIME_PATTERN = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')


class CheckConfigWizard(models.TransientModel):
    """Settings dialog for the spot check automation, reachable from the
    Device Management configuration menu instead of the technical
    system parameters screen."""
    _name = 'sn.wsd.device.check.config'
    _description = 'Spot Check Settings'

    trigger_time = fields.Char(
        string='Daily Trigger Time', required=True,
        help='Format HH:MM. Once this time is reached, the shared scheduled '
             'action generates the day\'s spot check tasks for every due '
             'plan. Applies to all plans; takes effect the next day.')

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
        return {'type': 'ir.actions.act_window_close'}
