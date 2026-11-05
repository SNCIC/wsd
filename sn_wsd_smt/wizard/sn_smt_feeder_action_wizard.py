from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SnSmtFeederActionWizard(models.TransientModel):
    _name = 'sn.smt.feeder.action.wizard'
    _description = 'SMT Feeder Lifecycle Action'

    action = fields.Selection(
        [
            ('report_repair', 'Report Repair'),
            ('complete_repair', 'Complete Repair'),
            ('scrap', 'Scrap'),
        ],
        string='Action',
        required=True,
    )
    feeder_id = fields.Many2one(
        'sn.smt.feeder',
        string='FEEDER_SN',
        required=True,
    )
    fault_desc = fields.Text(string='Fault Description')
    result = fields.Text(string='Repair Result')
    reason = fields.Text(string='Reason')

    @api.constrains('action', 'fault_desc')
    def _check_fault_desc(self):
        for wizard in self:
            if wizard.action == 'report_repair' and not wizard.fault_desc:
                raise ValidationError(_('The fault description is required.'))

    def action_confirm(self):
        self.ensure_one()
        feeder = self.feeder_id
        if self.action == 'report_repair':
            feeder.action_report_repair(self.fault_desc)
        elif self.action == 'complete_repair':
            feeder.action_complete_repair(self.result)
        else:
            feeder.action_scrap(self.reason or _('Manual scrap.'))
        return {'type': 'ir.actions.act_window_close'}
