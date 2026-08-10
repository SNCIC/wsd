from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class ToolingMaintenanceWizard(models.TransientModel):
    _name = 'sn.tooling.maintenance.wizard'
    _description = 'Tooling Maintenance Wizard'

    tooling_ids = fields.Many2many('sn.tooling', string='Tooling', required=True)
    product_tmpl_id = fields.Many2one('product.template', string='Tool Product', compute='_compute_product_tmpl_id')
    line_ids = fields.One2many('sn.tooling.maintenance.wizard.line', 'wizard_id', string='Maintenance Items')

    @api.depends('tooling_ids')
    def _compute_product_tmpl_id(self):
        for wizard in self:
            wizard.product_tmpl_id = wizard.tooling_ids[:1].product_tmpl_id

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        tooling_ids = self.env.context.get('default_tooling_ids', [])
        if tooling_ids:
            tooling_records = self.env['sn.tooling'].browse(tooling_ids)
            line_values = []
            template = tooling_records[:1].template_id
            for item in template.maintenance_item_ids:
                line_values.append(Command.create({
                    'name': item.name,
                    'result': item.default_result,
                    'note': item.note,
                }))
            result['line_ids'] = line_values
        return result

    def _validate_tooling(self):
        self.ensure_one()
        if not self.tooling_ids:
            raise UserError('Please select at least one tooling record.')
        products = self.tooling_ids.mapped('product_tmpl_id')
        if len(products) > 1:
            raise UserError('All tooling selected for batch maintenance must share the same product.')
        invalid_tooling = self.tooling_ids.filtered(lambda tooling: tooling.maintenance_status not in ('due', 'expired'))
        if invalid_tooling:
            raise UserError('Only due or expired tooling can be maintained.')

    def action_apply(self):
        self.ensure_one()
        self._validate_tooling()
        item_results = {
            tooling.id: [
                {'name': line.name, 'result': line.result, 'note': line.note}
                for line in self.line_ids
            ]
            for tooling in self.tooling_ids
        }
        self.tooling_ids.action_finish_maintenance(item_results)
        return {'type': 'ir.actions.act_window_close'}


class ToolingMaintenanceWizardLine(models.TransientModel):
    _name = 'sn.tooling.maintenance.wizard.line'
    _description = 'Tooling Maintenance Wizard Line'
    _order = 'id'

    wizard_id = fields.Many2one('sn.tooling.maintenance.wizard', required=True, ondelete='cascade')
    name = fields.Char(string='Item Name', required=True)
    result = fields.Selection(
        [('done', 'Done'), ('skipped', 'Skipped'), ('issue', 'Issue Found')],
        string='Result',
        required=True,
        default='done',
    )
    note = fields.Char(string='Note')
