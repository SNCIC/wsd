from odoo import api, fields, models


class SnToolingMaintainWizard(models.TransientModel):
    _name = 'sn.tooling.maintain.wizard'
    _description = 'Tooling Maintain Wizard'

    tooling_id = fields.Many2one('sn.tooling', string='Tooling SN', required=True)
    tension = fields.Float(string='Tension')
    thickness = fields.Float(string='Thickness (μm)')
    flatness = fields.Float(string='Flatness (μm)')
    line_ids = fields.One2many(
        'sn.tooling.maintain.wizard.line', 'wizard_id', string='Check Items')

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        tooling = self.env['sn.tooling'].browse(defaults.get('tooling_id'))
        if not tooling.exists():
            return defaults
        defaults.update({
            'tension': tooling.tension,
            'thickness': tooling.thickness,
            'flatness': tooling.flatness,
            'line_ids': [
                (0, 0, {
                    'sequence': item.sequence,
                    'name': item.name,
                    'result': item.default_result,
                    'note': item.note,
                })
                for item in tooling.template_id.maintenance_item_ids
            ],
        })
        return defaults

    def action_confirm(self):
        self.ensure_one()
        params = {
            'tension': self.tension,
            'thickness': self.thickness,
            'flatness': self.flatness,
        }
        line_vals = [
            (0, 0, {
                'sequence': line.sequence,
                'name': line.name,
                'result': line.result,
                'note': line.note,
            })
            for line in self.line_ids
        ]
        self.tooling_id.action_maintain_done(line_vals=line_vals, params=params)
        return {'type': 'ir.actions.act_window_close'}


class SnToolingMaintainWizardLine(models.TransientModel):
    _name = 'sn.tooling.maintain.wizard.line'
    _description = 'Tooling Maintain Wizard Line'

    wizard_id = fields.Many2one(
        'sn.tooling.maintain.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Item Name', required=True)
    result = fields.Selection(
        [
            ('done', 'Done'),
            ('skipped', 'Skipped'),
            ('issue', 'Issue Found'),
        ],
        string='Result', default='done', required=True)
    note = fields.Char(string='Note')


class SnToolingRepairStartWizard(models.TransientModel):
    _name = 'sn.tooling.repair.start.wizard'
    _description = 'Tooling Repair Start Wizard'

    tooling_id = fields.Many2one('sn.tooling', string='Tooling SN', required=True)
    fault = fields.Char(string='Fault', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.tooling_id.action_repair_start(self.fault)
        return {'type': 'ir.actions.act_window_close'}


class SnToolingRepairDoneWizard(models.TransientModel):
    _name = 'sn.tooling.repair.done.wizard'
    _description = 'Tooling Repair Done Wizard'

    tooling_id = fields.Many2one('sn.tooling', string='Tooling SN', required=True)
    outcome = fields.Selection(
        [('fixed', 'Repaired'), ('scrap', 'Cannot Repair - Scrap')],
        string='Outcome', default='fixed', required=True)
    reason = fields.Char(string='Scrap Reason')

    def action_confirm(self):
        self.ensure_one()
        self.tooling_id.action_repair_done(self.outcome, reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}


class SnToolingDisableWizard(models.TransientModel):
    _name = 'sn.tooling.disable.wizard'
    _description = 'Tooling Disable Wizard'

    tooling_id = fields.Many2one('sn.tooling', string='Tooling SN', required=True)
    reason = fields.Char(string='Disable Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.tooling_id.action_disable(self.reason)
        return {'type': 'ir.actions.act_window_close'}


class SnToolingScrapWizard(models.TransientModel):
    _name = 'sn.tooling.scrap.wizard'
    _description = 'Tooling Scrap Wizard'

    tooling_id = fields.Many2one('sn.tooling', string='Tooling SN', required=True)
    reason = fields.Char(string='Scrap Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.tooling_id.action_scrap(self.reason)
        return {'type': 'ir.actions.act_window_close'}
