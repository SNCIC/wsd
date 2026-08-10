from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    x_tooling_required = fields.Boolean(string='Tooling Required', compute='_compute_x_tooling_fields')
    x_available_tooling_ids = fields.Many2many('sn.tooling', string='Available Tooling', compute='_compute_x_tooling_fields')
    x_tooling_id = fields.Many2one(
        'sn.tooling',
        string='Tooling',
        check_company=True,
        copy=False,
        domain="[('id', 'in', x_available_tooling_ids)]",
    )
    x_tooling_usage_count = fields.Integer(string='Tooling Usage Count', compute='_compute_x_tooling_usage_count')
    x_tooling_usage_log_ids = fields.One2many('sn.tooling.usage.log', 'workorder_id', string='Tooling Usage Logs')

    @api.depends('product_id', 'production_bom_id', 'operation_id', 'workcenter_id', 'company_id')
    def _compute_x_tooling_fields(self):
        applicability_model = self.env['sn.tooling.applicability']
        tooling_model = self.env['sn.tooling']
        for workorder in self:
            if not workorder.product_id or not workorder.company_id:
                workorder.x_tooling_required = False
                workorder.x_available_tooling_ids = tooling_model
                continue
            matching_applicability = applicability_model.search([
                ('active', '=', True),
                ('company_id', '=', workorder.company_id.id),
                ('product_tmpl_id', '=', workorder.product_id.product_tmpl_id.id),
                '|', ('product_id', '=', False), ('product_id', '=', workorder.product_id.id),
                '|', ('bom_id', '=', False), ('bom_id', '=', workorder.production_bom_id.id),
                '|', ('operation_id', '=', False), ('operation_id', '=', workorder.operation_id.id),
                '|', ('workcenter_id', '=', False), ('workcenter_id', '=', workorder.workcenter_id.id),
            ], order='sequence, id')
            workorder.x_tooling_required = bool(matching_applicability)
            workorder.x_available_tooling_ids = matching_applicability.mapped('tooling_id').filtered(
                lambda tooling: tooling.state in ('in_stock', 'issued', 'online') and tooling.maintenance_status != 'expired'
            )

    @api.depends('x_tooling_usage_log_ids')
    def _compute_x_tooling_usage_count(self):
        for workorder in self:
            workorder.x_tooling_usage_count = len(workorder.x_tooling_usage_log_ids)

    @api.onchange('product_id', 'production_bom_id', 'operation_id', 'workcenter_id')
    def _onchange_x_tooling_scope(self):
        for workorder in self:
            if not workorder.x_tooling_required:
                workorder.x_tooling_id = False
                continue
            if workorder.x_tooling_id and workorder.x_tooling_id not in workorder.x_available_tooling_ids:
                workorder.x_tooling_id = False

    @api.onchange('x_tooling_id')
    def _onchange_x_tooling_id(self):
        if self.x_tooling_id:
            self.x_tooling_id._check_workorder_match(self)

    def action_open_tooling_pda_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tooling PDA Operation'),
            'res_model': 'sn.tooling.pda.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_workorder_id': self.id,
                'default_tooling_id': self.x_tooling_id.id,
            },
        }

    def action_register_tooling_usage(self, pass_qty=None, tooling=False, note=None):
        for workorder in self:
            target_tooling = tooling or workorder.x_tooling_id
            if not target_tooling:
                continue
            qty = pass_qty if pass_qty is not None else int(workorder.x_meter_qty_pass or workorder.qty_producing or 0)
            if qty > 0:
                target_tooling.action_register_usage(qty, workorder=workorder, note=note)

    def _ensure_tooling_ready_for_start(self):
        self.ensure_one()
        if not self.x_tooling_id:
            if self.x_tooling_required:
                raise UserError(_('A tooling selection is required before starting this work order.'))
            return
        if self.x_tooling_id.state == 'in_stock':
            self.x_tooling_id.action_pda_issue(workorder=self, note=_('Automatically issued from work order start'))
        if self.x_tooling_id.state == 'issued':
            self.x_tooling_id.action_pda_online(workorder=self, note=_('Automatically put online from work order start'))

    def button_start(self, raise_on_invalid_state=False):
        for workorder in self:
            workorder._ensure_tooling_ready_for_start()
        return super().button_start(raise_on_invalid_state=raise_on_invalid_state)

    def button_finish(self):
        result = super().button_finish()
        for workorder in self:
            workorder.action_register_tooling_usage()
            if workorder.x_tooling_id and workorder.x_tooling_id.state == 'online':
                workorder.x_tooling_id.action_pda_offline(workorder=workorder, note=_('Automatically taken offline from work order completion'))
        return result
