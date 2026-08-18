from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


TOOL_TYPE_SELECTION = [
    ('stencil', 'Stencil'),
    ('squeegee', 'Squeegee'),
    ('mold', 'Mold'),
]

TOOL_STATE_SELECTION = [
    ('draft', 'Draft'),
    ('in_stock', 'In Stock'),
    ('issued', 'Issued'),
    ('online', 'Online'),
    ('cleaning', 'Cleaning'),
    ('disabled', 'Disabled'),
    ('scrapped', 'Scrapped'),
]

MAINTENANCE_STATUS_SELECTION = [
    ('normal', 'Normal'),
    ('due', 'Due'),
    ('expired', 'Expired'),
]

OPERATION_TYPE_SELECTION = [
    ('issue', 'Issue'),
    ('online', 'Online'),
    ('offline', 'Offline'),
    ('cleaning', 'Cleaning'),
    ('return', 'Return'),
]

MAINTENANCE_RESULT_SELECTION = [
    ('done', 'Done'),
    ('skipped', 'Skipped'),
    ('issue', 'Issue Found'),
]


class ToolingTemplate(models.Model):
    _name = 'sn.tooling.template'
    _description = 'Tooling Template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code, id'
    _check_company_auto = True

    name = fields.Char(string='Template Name', required=True, tracking=True)
    code = fields.Char(string='Template Code', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    tool_type = fields.Selection(TOOL_TYPE_SELECTION, string='Tool Type', required=True, default='stencil', tracking=True)
    product_tmpl_id = fields.Many2one('product.template', string='Tool Product', required=True, check_company=True, tracking=True)
    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        check_company=True,
        tracking=True,
    )
    spec = fields.Char(string='Specification', tracking=True)
    panel_count = fields.Integer(string='Panel Count', default=1, tracking=True)
    safe_stock_qty = fields.Integer(string='Safe Stock', default=0, tracking=True)
    maintenance_by_count = fields.Boolean(string='Enable Count Maintenance', default=True, tracking=True)
    maintenance_count_limit = fields.Integer(string='Maintenance Count Limit', default=0, tracking=True)
    maintenance_count_reminder = fields.Integer(string='Count Reminder Threshold', default=0, tracking=True)
    maintenance_by_cycle = fields.Boolean(string='Enable Cycle Maintenance', default=False, tracking=True)
    maintenance_cycle_days = fields.Integer(string='Maintenance Cycle Days', default=0, tracking=True)
    maintenance_cycle_reminder_days = fields.Integer(string='Cycle Reminder Days', default=0, tracking=True)
    maintenance_item_ids = fields.One2many('sn.tooling.template.maintenance.item', 'template_id', string='Maintenance Items')
    note = fields.Html(string='Notes')
    tooling_ids = fields.One2many('sn.tooling', 'template_id', string='Tooling')
    tooling_count = fields.Integer(compute='_compute_tooling_count')

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        'Template code must be unique per company.',
    )

    @api.depends('tooling_ids')
    def _compute_tooling_count(self):
        for template in self:
            template.tooling_count = len(template.tooling_ids)

    @api.constrains('panel_count')
    def _check_panel_count(self):
        for template in self:
            if template.panel_count <= 0:
                raise ValidationError(_('Panel count must be greater than zero.'))

    @api.constrains('maintenance_count_limit', 'maintenance_count_reminder', 'maintenance_cycle_days', 'maintenance_cycle_reminder_days')
    def _check_maintenance_params(self):
        for template in self:
            if template.maintenance_count_reminder < 0 or template.maintenance_cycle_reminder_days < 0:
                raise ValidationError(_('Maintenance reminder values cannot be negative.'))
            if template.maintenance_count_limit and template.maintenance_count_reminder > template.maintenance_count_limit:
                raise ValidationError(_('Count reminder cannot exceed maintenance count limit.'))
            if template.maintenance_cycle_days and template.maintenance_cycle_reminder_days > template.maintenance_cycle_days:
                raise ValidationError(_('Cycle reminder cannot exceed maintenance cycle days.'))

    def action_view_tooling(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tooling'),
            'res_model': 'sn.tooling',
            'view_mode': 'list,form',
            'domain': [('template_id', '=', self.id)],
            'context': {'default_template_id': self.id},
        }


class ToolingTemplateMaintenanceItem(models.Model):
    _name = 'sn.tooling.template.maintenance.item'
    _description = 'Tooling Template Maintenance Item'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one('sn.tooling.template', required=True, ondelete='cascade')
    name = fields.Char(string='Item Name', required=True)
    default_result = fields.Selection(MAINTENANCE_RESULT_SELECTION, string='Default Result', default='done', required=True)
    note = fields.Char(string='Instruction')


class Tooling(models.Model):
    _name = 'sn.tooling'
    _description = 'Tooling'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Tooling Code', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    template_id = fields.Many2one('sn.tooling.template', string='Tooling Template', check_company=True, tracking=True)
    tool_type = fields.Selection(TOOL_TYPE_SELECTION, string='Tool Type', required=True, default='stencil', tracking=True)
    product_tmpl_id = fields.Many2one('product.template', string='Tool Product', required=True, check_company=True, tracking=True)
    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        check_company=True,
        tracking=True,
    )
    spec = fields.Char(string='Specification', tracking=True)
    panel_count = fields.Integer(string='Panel Count', default=1, tracking=True)
    safe_stock_qty = fields.Integer(string='Safe Stock', default=0, tracking=True)
    bom_id = fields.Many2one('mrp.bom', string='BoM', check_company=True, tracking=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Default Work Center', check_company=True, tracking=True)
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        domain="[('usage', '=', 'internal')]",
        check_company=True,
        tracking=True,
    )
    vendor_id = fields.Many2one('res.partner', string='Vendor', check_company=True, tracking=True)
    maintenance_equipment_id = fields.Many2one(
        'maintenance.equipment',
        string='Maintenance Equipment',
        check_company=True,
        copy=False,
    )
    manufacture_date = fields.Date(string='Manufacture Date')
    acceptance_date = fields.Date(string='Acceptance Date')
    state = fields.Selection(TOOL_STATE_SELECTION, string='State', default='draft', required=True, tracking=True)
    maintenance_by_count = fields.Boolean(string='Enable Count Maintenance', default=True, tracking=True)
    maintenance_count_limit = fields.Integer(string='Maintenance Count Limit', default=0, tracking=True)
    maintenance_count_reminder = fields.Integer(string='Count Reminder Threshold', default=0, tracking=True)
    maintenance_by_cycle = fields.Boolean(string='Enable Cycle Maintenance', default=False, tracking=True)
    maintenance_cycle_days = fields.Integer(string='Maintenance Cycle Days', default=0, tracking=True)
    maintenance_cycle_reminder_days = fields.Integer(string='Cycle Reminder Days', default=0, tracking=True)
    last_maintenance_date = fields.Date(string='Last Maintenance Date', tracking=True)
    maintenance_status = fields.Selection(
        MAINTENANCE_STATUS_SELECTION,
        string='Maintenance Status',
        compute='_compute_maintenance_status',
        store=True,
        tracking=True,
    )
    count_maintenance_status = fields.Selection(
        MAINTENANCE_STATUS_SELECTION,
        string='Count Maintenance Status',
        compute='_compute_maintenance_status',
        store=True,
    )
    cycle_maintenance_status = fields.Selection(
        MAINTENANCE_STATUS_SELECTION,
        string='Cycle Maintenance Status',
        compute='_compute_maintenance_status',
        store=True,
    )
    current_usage_count = fields.Integer(string='Current Usage Count', default=0, tracking=True)
    total_usage_count = fields.Integer(string='Total Usage Count', default=0, tracking=True)
    next_count_maintenance_at = fields.Integer(string='Next Count Maintenance Threshold', compute='_compute_next_maintenance_metrics', store=True)
    next_cycle_maintenance_date = fields.Date(string='Next Cycle Maintenance Date', compute='_compute_next_maintenance_metrics', store=True)
    disabled_reason = fields.Char(string='Disable Reason')
    scrap_reason = fields.Char(string='Scrap Reason', tracking=True)
    scrap_user_id = fields.Many2one('res.users', string='Scrapped By', readonly=True)
    scrap_date = fields.Datetime(string='Scrap Date', readonly=True)
    note = fields.Html(string='Notes')
    applicability_ids = fields.One2many('sn.tooling.applicability', 'tooling_id', string='Applicability')
    operation_log_ids = fields.One2many('sn.tooling.operation.log', 'tooling_id', string='Operation Logs')
    usage_log_ids = fields.One2many('sn.tooling.usage.log', 'tooling_id', string='Usage Logs')
    maintenance_log_ids = fields.One2many('sn.tooling.maintenance.log', 'tooling_id', string='Maintenance Logs')
    operation_count = fields.Integer(compute='_compute_counters')
    usage_count = fields.Integer(compute='_compute_counters')
    maintenance_log_count = fields.Integer(compute='_compute_counters')
    maintenance_request_count = fields.Integer(compute='_compute_counters')

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        'Tooling code must be unique per company.',
    )

    @api.depends('current_usage_count', 'maintenance_count_limit', 'last_maintenance_date', 'maintenance_cycle_days')
    def _compute_next_maintenance_metrics(self):
        for tooling in self:
            tooling.next_count_maintenance_at = tooling.maintenance_count_limit or 0
            if tooling.last_maintenance_date and tooling.maintenance_cycle_days > 0:
                tooling.next_cycle_maintenance_date = tooling.last_maintenance_date + relativedelta(days=tooling.maintenance_cycle_days)
            else:
                tooling.next_cycle_maintenance_date = False

    @api.depends(
        'current_usage_count',
        'maintenance_by_count',
        'maintenance_count_limit',
        'maintenance_count_reminder',
        'maintenance_by_cycle',
        'maintenance_cycle_days',
        'maintenance_cycle_reminder_days',
        'last_maintenance_date',
    )
    def _compute_maintenance_status(self):
        severity_rank = {'normal': 0, 'due': 1, 'expired': 2}
        today = fields.Date.context_today(self)
        for tooling in self:
            count_status = 'normal'
            cycle_status = 'normal'
            if tooling.maintenance_by_count and tooling.maintenance_count_limit > 0:
                due_start = max(tooling.maintenance_count_limit - tooling.maintenance_count_reminder, 0)
                if tooling.current_usage_count >= tooling.maintenance_count_limit:
                    count_status = 'expired'
                elif tooling.current_usage_count >= due_start:
                    count_status = 'due'
            if tooling.maintenance_by_cycle and tooling.maintenance_cycle_days > 0 and tooling.last_maintenance_date:
                due_date = tooling.last_maintenance_date + relativedelta(days=tooling.maintenance_cycle_days)
                remind_date = due_date - relativedelta(days=tooling.maintenance_cycle_reminder_days or 0)
                if today >= due_date:
                    cycle_status = 'expired'
                elif today >= remind_date:
                    cycle_status = 'due'
            tooling.count_maintenance_status = count_status
            tooling.cycle_maintenance_status = cycle_status
            tooling.maintenance_status = max((count_status, cycle_status), key=lambda status: severity_rank[status])

    @api.depends('operation_log_ids', 'usage_log_ids', 'maintenance_log_ids', 'maintenance_equipment_id.maintenance_ids')
    def _compute_counters(self):
        for tooling in self:
            tooling.operation_count = len(tooling.operation_log_ids)
            tooling.usage_count = len(tooling.usage_log_ids)
            tooling.maintenance_log_count = len(tooling.maintenance_log_ids)
            tooling.maintenance_request_count = len(tooling.maintenance_equipment_id.maintenance_ids)

    @api.constrains('panel_count')
    def _check_panel_count(self):
        for tooling in self:
            if tooling.panel_count <= 0:
                raise ValidationError(_('Panel count must be greater than zero.'))

    @api.constrains('maintenance_count_limit', 'maintenance_count_reminder', 'maintenance_cycle_days', 'maintenance_cycle_reminder_days')
    def _check_maintenance_params(self):
        for tooling in self:
            if tooling.maintenance_count_reminder < 0 or tooling.maintenance_cycle_reminder_days < 0:
                raise ValidationError(_('Maintenance reminder values cannot be negative.'))
            if tooling.maintenance_count_limit and tooling.maintenance_count_reminder > tooling.maintenance_count_limit:
                raise ValidationError(_('Count reminder cannot exceed maintenance count limit.'))
            if tooling.maintenance_cycle_days and tooling.maintenance_cycle_reminder_days > tooling.maintenance_cycle_days:
                raise ValidationError(_('Cycle reminder cannot exceed maintenance cycle days.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create([self._prepare_vals_from_template(vals) for vals in vals_list])
        records._ensure_maintenance_equipment()
        return records

    def write(self, vals):
        vals = self._prepare_vals_from_template(vals, partial=True)
        result = super().write(vals)
        self._ensure_maintenance_equipment()
        return result

    def _prepare_vals_from_template(self, vals, partial=False):
        template_id = vals.get('template_id')
        if not template_id:
            return vals
        template = self.env['sn.tooling.template'].browse(template_id)
        if not template:
            return vals
        defaults = {
            'tool_type': template.tool_type,
            'product_tmpl_id': template.product_tmpl_id.id,
            'product_id': template.product_id.id,
            'spec': template.spec,
            'panel_count': template.panel_count,
            'safe_stock_qty': template.safe_stock_qty,
            'maintenance_by_count': template.maintenance_by_count,
            'maintenance_count_limit': template.maintenance_count_limit,
            'maintenance_count_reminder': template.maintenance_count_reminder,
            'maintenance_by_cycle': template.maintenance_by_cycle,
            'maintenance_cycle_days': template.maintenance_cycle_days,
            'maintenance_cycle_reminder_days': template.maintenance_cycle_reminder_days,
        }
        for key, value in defaults.items():
            if key not in vals or (not partial and vals.get(key) in (False, None, '')):
                vals.setdefault(key, value)
        return vals

    def _ensure_maintenance_equipment(self):
        category = self.env['maintenance.equipment.category'].search([('name', '=', 'Tooling')], limit=1)
        for tooling in self.filtered(lambda record: not record.maintenance_equipment_id):
            tooling.maintenance_equipment_id = self.env['maintenance.equipment'].create({
                'name': tooling.name,
                'category_id': category.id if category else False,
                'company_id': tooling.company_id.id,
                'owner_user_id': self.env.user.id,
                'serial_no': tooling.name,
                'partner_id': tooling.vendor_id.id,
                'effective_date': tooling.acceptance_date or fields.Date.context_today(self),
                'note': tooling.note,
            })

    def _check_workorder_match(self, workorder):
        self.ensure_one()
        if self.product_tmpl_id != workorder.product_id.product_tmpl_id:
            raise UserError(_('Tooling %s does not match the work order product.') % self.display_name)
        if self.workcenter_id and self.workcenter_id != workorder.workcenter_id:
            raise UserError(_('Tooling %s is not applicable to the current work center.') % self.display_name)
        applicable = self.applicability_ids.filtered(lambda line: line._matches_workorder(workorder))
        if self.applicability_ids and not applicable:
            raise UserError(_('Tooling %s has no applicability mapping for the current work order.') % self.display_name)

    def _check_can_issue(self, workorder=None):
        self.ensure_one()
        if self.state != 'in_stock':
            raise UserError(_('Only in-stock tooling can be issued.'))
        if self.maintenance_status == 'expired':
            raise UserError(_('Tooling %s has expired maintenance and cannot be issued.') % self.display_name)
        if workorder:
            self._check_workorder_match(workorder)

    def _check_can_online(self, workorder=None):
        self.ensure_one()
        if self.state != 'issued':
            raise UserError(_('Only issued tooling can be put online.'))
        if self.maintenance_status == 'expired':
            raise UserError(_('Tooling %s has expired maintenance and cannot be put online.') % self.display_name)
        if workorder:
            self._check_workorder_match(workorder)

    def _create_operation_log(self, operation_type, workorder=False, note=False):
        self.ensure_one()
        return self.env['sn.tooling.operation.log'].create({
            'tooling_id': self.id,
            'workorder_id': workorder.id if workorder else False,
            'operation_type': operation_type,
            'operator_id': self.env.user.id,
            'operation_time': fields.Datetime.now(),
            'note': note,
        })

    def action_disable(self):
        for tooling in self:
            if tooling.state != 'in_stock':
                raise UserError(_('Only in-stock tooling can be disabled.'))
        self.write({'state': 'disabled'})

    def action_enable(self):
        for tooling in self:
            if tooling.state != 'disabled':
                raise UserError(_('Only disabled tooling can be enabled.'))
        self.write({'state': 'in_stock', 'disabled_reason': False})

    def action_scrap(self):
        for tooling in self:
            if tooling.state == 'online':
                raise UserError(_('Online tooling must be taken offline before scrapping.'))
            if not tooling.scrap_reason:
                raise UserError(_('A scrap reason is required before scrapping.'))
        self.write({
            'state': 'scrapped',
            'scrap_user_id': self.env.user.id,
            'scrap_date': fields.Datetime.now(),
        })

    def action_view_operation_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Operation Logs'),
            'res_model': 'sn.tooling.operation.log',
            'view_mode': 'list,form',
            'domain': [('tooling_id', '=', self.id)],
            'context': {'default_tooling_id': self.id},
        }

    def action_view_usage_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Usage Logs'),
            'res_model': 'sn.tooling.usage.log',
            'view_mode': 'list,form',
            'domain': [('tooling_id', '=', self.id)],
            'context': {'default_tooling_id': self.id},
        }

    def action_view_maintenance_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Logs'),
            'res_model': 'sn.tooling.maintenance.log',
            'view_mode': 'list,form',
            'domain': [('tooling_id', '=', self.id)],
            'context': {'default_tooling_id': self.id},
        }

    def action_view_maintenance_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Requests'),
            'res_model': 'maintenance.request',
            'view_mode': 'list,form',
            'domain': [('equipment_id', '=', self.maintenance_equipment_id.id)],
            'context': {'default_equipment_id': self.maintenance_equipment_id.id},
        }

    def action_open_maintenance_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Batch Maintenance'),
            'res_model': 'sn.tooling.maintenance.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_tooling_ids': self.ids},
        }

    def action_pda_issue(self, workorder=False, note=False):
        for tooling in self:
            tooling._check_can_issue(workorder=workorder)
            if tooling.maintenance_status == 'due':
                tooling.message_post(body=_('Tooling was issued while maintenance status was Due.'))
            tooling.state = 'issued'
            tooling._create_operation_log('issue', workorder=workorder, note=note)

    def action_pda_online(self, workorder=False, note=False):
        for tooling in self:
            tooling._check_can_online(workorder=workorder)
            if tooling.maintenance_status == 'due':
                tooling.message_post(body=_('Tooling was put online while maintenance status was Due.'))
            tooling.state = 'online'
            tooling._create_operation_log('online', workorder=workorder, note=note)

    def action_pda_offline(self, workorder=False, note=False):
        for tooling in self:
            if tooling.state != 'online':
                raise UserError(_('Only online tooling can be taken offline.'))
            tooling.state = 'in_stock'
            tooling._create_operation_log('offline', workorder=workorder, note=note)

    def action_pda_cleaning(self, workorder=False, note=False):
        for tooling in self:
            if tooling.state != 'in_stock':
                raise UserError(_('Only in-stock tooling can be moved to cleaning.'))
            tooling.state = 'cleaning'
            tooling._create_operation_log('cleaning', workorder=workorder, note=note)

    def action_pda_return(self, workorder=False, note=False):
        for tooling in self:
            if tooling.state != 'issued':
                raise UserError(_('Only issued tooling can be returned.'))
            tooling.state = 'in_stock'
            tooling._create_operation_log('return', workorder=workorder, note=note)

    def action_register_usage(self, pass_qty, panel_count=False, workorder=False, note=False):
        for tooling in self:
            multiplier = panel_count or tooling.panel_count or 1
            usage_qty = int(pass_qty * multiplier)
            if usage_qty <= 0:
                raise UserError(_('Usage quantity must be greater than zero.'))
            tooling.write({
                'total_usage_count': tooling.total_usage_count + usage_qty,
                'current_usage_count': tooling.current_usage_count + usage_qty,
            })
            self.env['sn.tooling.usage.log'].create({
                'tooling_id': tooling.id,
                'workorder_id': workorder.id if workorder else False,
                'operator_id': self.env.user.id,
                'operation_time': fields.Datetime.now(),
                'pass_qty': pass_qty,
                'panel_count': multiplier,
                'usage_qty': usage_qty,
                'note': note,
            })

    def action_finish_maintenance(self, item_results):
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        for tooling in self:
            if tooling.maintenance_status not in ('due', 'expired'):
                raise UserError(_('Only due or expired tooling can be maintained.'))
            log = self.env['sn.tooling.maintenance.log'].create({
                'tooling_id': tooling.id,
                'maintenance_time': now,
                'maintenance_user_id': self.env.user.id,
                'before_status': tooling.maintenance_status,
                'before_current_usage_count': tooling.current_usage_count,
            })
            for item in item_results.get(tooling.id, []):
                self.env['sn.tooling.maintenance.log.line'].create({
                    'log_id': log.id,
                    'name': item['name'],
                    'result': item['result'],
                    'note': item.get('note'),
                })
            tooling.write({
                'last_maintenance_date': today,
                'current_usage_count': 0,
                'state': 'in_stock' if tooling.state not in ('scrapped', 'disabled') else tooling.state,
            })
            log.write({
                'after_status': tooling.maintenance_status,
                'after_current_usage_count': tooling.current_usage_count,
            })


class ToolingApplicability(models.Model):
    _name = 'sn.tooling.applicability'
    _description = 'Tooling Applicability'
    _order = 'sequence, id'
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='tooling_id.company_id', store=True)
    tooling_id = fields.Many2one('sn.tooling', required=True, ondelete='cascade')
    product_tmpl_id = fields.Many2one('product.template', string='Product', required=True, check_company=True)
    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        check_company=True,
    )
    bom_id = fields.Many2one('mrp.bom', string='BoM', check_company=True)
    operation_id = fields.Many2one('mrp.routing.workcenter', string='Operation', check_company=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', check_company=True)
    active = fields.Boolean(default=True)

    def _matches_workorder(self, workorder):
        self.ensure_one()
        return (
            self.active
            and self.product_tmpl_id == workorder.product_id.product_tmpl_id
            and (not self.product_id or self.product_id == workorder.product_id)
            and (not self.bom_id or self.bom_id == workorder.production_bom_id)
            and (not self.operation_id or self.operation_id == workorder.operation_id)
            and (not self.workcenter_id or self.workcenter_id == workorder.workcenter_id)
        )


class ToolingOperationLog(models.Model):
    _name = 'sn.tooling.operation.log'
    _description = 'Tooling Operation Log'
    _order = 'operation_time desc, id desc'
    _check_company_auto = True

    tooling_id = fields.Many2one('sn.tooling', string='Tooling', required=True, check_company=True)
    company_id = fields.Many2one(related='tooling_id.company_id', store=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', check_company=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='workorder_id.x_mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    operator_id = fields.Many2one('res.users', string='Operator', required=True, default=lambda self: self.env.user)
    operation_type = fields.Selection(OPERATION_TYPE_SELECTION, string='Operation Type', required=True)
    operation_time = fields.Datetime(string='Operation Time', required=True, default=fields.Datetime.now)
    note = fields.Char(string='Note')


class ToolingUsageLog(models.Model):
    _name = 'sn.tooling.usage.log'
    _description = 'Tooling Usage Log'
    _order = 'operation_time desc, id desc'
    _check_company_auto = True

    tooling_id = fields.Many2one('sn.tooling', string='Tooling', required=True, check_company=True)
    company_id = fields.Many2one(related='tooling_id.company_id', store=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', check_company=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='workorder_id.x_mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    operator_id = fields.Many2one('res.users', string='Operator', required=True, default=lambda self: self.env.user)
    operation_time = fields.Datetime(string='Pass Time', required=True, default=fields.Datetime.now)
    pass_qty = fields.Integer(string='Pass Quantity', required=True, default=0)
    panel_count = fields.Integer(string='Panel Count', required=True, default=1)
    usage_qty = fields.Integer(string='Usage Quantity', required=True, default=1)
    note = fields.Char(string='Note')

    @api.constrains('panel_count', 'usage_qty')
    def _check_usage(self):
        for log in self:
            if log.panel_count <= 0:
                raise ValidationError(_('Panel count must be greater than zero.'))
            if log.usage_qty <= 0:
                raise ValidationError(_('Usage count must be greater than zero.'))


class ToolingMaintenanceLog(models.Model):
    _name = 'sn.tooling.maintenance.log'
    _description = 'Tooling Maintenance Log'
    _order = 'maintenance_time desc, id desc'
    _check_company_auto = True

    tooling_id = fields.Many2one('sn.tooling', string='Tooling', required=True, check_company=True)
    company_id = fields.Many2one(related='tooling_id.company_id', store=True)
    maintenance_time = fields.Datetime(string='Maintenance Time', required=True, default=fields.Datetime.now)
    maintenance_user_id = fields.Many2one('res.users', string='Maintained By', required=True, default=lambda self: self.env.user)
    before_status = fields.Selection(MAINTENANCE_STATUS_SELECTION, string='Status Before Maintenance')
    after_status = fields.Selection(MAINTENANCE_STATUS_SELECTION, string='Status After Maintenance')
    before_current_usage_count = fields.Integer(string='Current Usage Before Maintenance')
    after_current_usage_count = fields.Integer(string='Current Usage After Maintenance')
    line_ids = fields.One2many('sn.tooling.maintenance.log.line', 'log_id', string='Maintenance Items')


class ToolingMaintenanceLogLine(models.Model):
    _name = 'sn.tooling.maintenance.log.line'
    _description = 'Tooling Maintenance Log Line'
    _order = 'id'

    log_id = fields.Many2one('sn.tooling.maintenance.log', required=True, ondelete='cascade')
    name = fields.Char(string='Item Name', required=True)
    result = fields.Selection(MAINTENANCE_RESULT_SELECTION, string='Result', default='done', required=True)
    note = fields.Char(string='Note')
