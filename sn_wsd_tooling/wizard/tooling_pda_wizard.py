from odoo import fields, models


class ToolingPdaWizard(models.TransientModel):
    _name = 'sn.tooling.pda.wizard'
    _description = 'Tooling PDA Wizard'

    route_operation_id = fields.Many2one('sn.wsd.mes.order.route.operation', string='MES Route Operation')
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
        operation_map[self.operation_type](route_operation=self.route_operation_id, note=self.note)
        return {'type': 'ir.actions.act_window_close'}
