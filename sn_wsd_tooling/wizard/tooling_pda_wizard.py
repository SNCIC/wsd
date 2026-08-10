from odoo import fields, models


class ToolingPdaWizard(models.TransientModel):
    _name = 'sn.tooling.pda.wizard'
    _description = 'Tooling PDA Wizard'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order')
    tooling_id = fields.Many2one('sn.tooling', string='Tooling', required=True)
    operation_type = fields.Selection(
        [
            ('issue', 'Issue'),
            ('online', 'Online'),
            ('offline', 'Offline'),
            ('cleaning', 'Cleaning'),
            ('return', 'Return'),
        ],
        string='Operation',
        required=True,
        default='issue',
    )
    note = fields.Char(string='Note')

    def action_apply(self):
        self.ensure_one()
        operation_map = {
            'issue': self.tooling_id.action_pda_issue,
            'online': self.tooling_id.action_pda_online,
            'offline': self.tooling_id.action_pda_offline,
            'cleaning': self.tooling_id.action_pda_cleaning,
            'return': self.tooling_id.action_pda_return,
        }
        operation_map[self.operation_type](workorder=self.workorder_id, note=self.note)
        if self.workorder_id and self.operation_type in ('issue', 'online'):
            self.workorder_id.x_tooling_id = self.tooling_id
        return {'type': 'ir.actions.act_window_close'}
