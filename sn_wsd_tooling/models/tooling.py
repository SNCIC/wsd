from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

TOOL_STATE_SELECTION = [
    ('idle', 'Idle'),
    ('issued', 'Issued'),
    ('online', 'Online'),
    ('maintaining', 'Maintaining'),
    ('repairing', 'Repairing'),
    ('disabled', 'Disabled'),
    ('scrapped', 'Scrapped'),
]

MAINTENANCE_STATUS_SELECTION = [
    ('normal', 'Normal'),
    ('due', 'Due'),
    ('expired', 'Expired'),
]

RECORD_ACTION_SELECTION = [
    ('issue', 'Issue'),
    ('return', 'Return'),
    ('online', 'Put Online'),
    ('offline', 'Take Offline'),
    ('usage', 'Usage'),
    ('maintain', 'Maintain'),
    ('repair', 'Repair'),
    ('disable', 'Disable'),
    ('enable', 'Enable'),
    ('scrap', 'Scrap'),
]

MAINTENANCE_RESULT_SELECTION = [
    ('done', 'Done'),
    ('skipped', 'Skipped'),
    ('issue', 'Issue Found'),
]


class SnToolingType(models.Model):
    _name = 'sn.tooling.type'
    _description = 'Tooling Type'
    _inherit = ['mail.thread']
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Type Name', required=True, tracking=True)
    code = fields.Char(string='Type Code')
    has_tension = fields.Boolean(
        string='Enable Tension',
        help='Show the tension parameter on templates and tooling of this type.')
    has_thickness = fields.Boolean(
        string='Enable Thickness',
        help='Show the thickness parameter on templates and tooling of this type.')
    has_flatness = fields.Boolean(
        string='Enable Flatness',
        help='Show the flatness parameter on templates and tooling of this type.')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_tooling_type_name_unique = models.Constraint(
        'unique(company_id, name)',
        'The tooling type name must be unique per company.',
    )
    _sn_tooling_type_code_unique = models.Constraint(
        'unique(company_id, code)',
        'The tooling type code must be unique per company.',
    )


class SnToolingTemplate(models.Model):
    _name = 'sn.tooling.template'
    _description = 'Tooling Template'
    _inherit = ['mail.thread']
    _order = 'code, id'
    _check_company_auto = True

    code = fields.Char(string='Tooling Code', required=True, index=True, tracking=True)
    name = fields.Char(string='Tooling Name', required=True, tracking=True)
    spec = fields.Char(string='Specification')
    type_id = fields.Many2one(
        'sn.tooling.type',
        string='Tooling Type',
        required=True,
        index=True,
        ondelete='restrict',
        check_company=True,
        tracking=True,
    )
    supplier_id = fields.Many2one(
        'res.partner', string='Supplier', check_company=True, tracking=True)
    maintenance_by_count = fields.Boolean(string='Maintenance by Count', default=True)
    maintenance_count_limit = fields.Integer(string='Maintenance Count Limit', default=0, tracking=True)
    maintenance_count_reminder = fields.Integer(string='Count Reminder Threshold', default=0)
    maintenance_by_cycle = fields.Boolean(string='Maintenance by Cycle', default=False)
    maintenance_cycle_days = fields.Integer(string='Maintenance Cycle (days)', default=0, tracking=True)
    maintenance_cycle_reminder_days = fields.Integer(string='Cycle Reminder (days)', default=0)
    maintenance_item_ids = fields.One2many(
        'sn.tooling.template.maintenance.item', 'template_id', string='Maintenance Items')
    default_tension = fields.Float(string='Default Tension')
    default_thickness = fields.Float(string='Default Thickness (μm)')
    default_flatness = fields.Float(string='Default Flatness (μm)')
    note = fields.Text(string='Notes')
    active = fields.Boolean(default=True)
    tooling_ids = fields.One2many('sn.tooling', 'template_id', string='Tooling')
    tooling_count = fields.Integer(string='Tooling', compute='_compute_tooling_count')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_tooling_template_code_unique = models.Constraint(
        'unique(company_id, code)',
        'The tooling code must be unique per company.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for template in self:
            template.display_name = ' - '.join(
                part for part in (template.code, template.name) if part)

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        if name:
            domain = list(domain or []) + [
                '|', ('code', operator, name), ('name', operator, name)]
            return super().name_search('', domain=domain, operator='ilike', limit=limit)
        return super().name_search(name, domain=domain, operator=operator, limit=limit)

    @api.depends('tooling_ids')
    def _compute_tooling_count(self):
        for template in self:
            template.tooling_count = len(template.tooling_ids)

    @api.constrains(
        'maintenance_count_limit',
        'maintenance_count_reminder',
        'maintenance_cycle_days',
        'maintenance_cycle_reminder_days')
    def _check_maintenance_params(self):
        for template in self:
            if template.maintenance_count_reminder < 0 or template.maintenance_cycle_reminder_days < 0:
                raise ValidationError(_('Maintenance reminder values cannot be negative.'))
            if template.maintenance_count_limit and \
                    template.maintenance_count_reminder > template.maintenance_count_limit:
                raise ValidationError(_(
                    'The count reminder threshold cannot exceed the maintenance count limit.'))
            if template.maintenance_cycle_days and \
                    template.maintenance_cycle_reminder_days > template.maintenance_cycle_days:
                raise ValidationError(_(
                    'The cycle reminder days cannot exceed the maintenance cycle days.'))

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


class SnToolingTemplateMaintenanceItem(models.Model):
    _name = 'sn.tooling.template.maintenance.item'
    _description = 'Tooling Template Maintenance Item'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one(
        'sn.tooling.template', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Item Name', required=True)
    default_result = fields.Selection(
        MAINTENANCE_RESULT_SELECTION, string='Default Result', default='done', required=True)
    note = fields.Char(string='Instruction')


class SnTooling(models.Model):
    _name = 'sn.tooling'
    _description = 'Tooling'
    _inherit = ['mail.thread']
    _order = 'sn, id'
    _rec_name = 'sn'
    _check_company_auto = True

    sn = fields.Char(string='Tooling SN', required=True, index=True, tracking=True)
    template_id = fields.Many2one(
        'sn.tooling.template',
        string='Tooling Code',
        required=True,
        ondelete='restrict',
        index=True,
        check_company=True,
        tracking=True,
    )
    type_id = fields.Many2one(
        related='template_id.type_id', store=True, index=True)
    spec = fields.Char(related='template_id.spec')
    tension = fields.Float(string='Tension')
    thickness = fields.Float(string='Thickness (μm)')
    flatness = fields.Float(string='Flatness (μm)')
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        domain="[('usage', '=', 'internal')]",
        check_company=True,
    )
    manufacture_date = fields.Date(string='Manufacture Date', default=fields.Date.today)
    total_usage_count = fields.Integer(
        string='Total Usage Count', default=0, copy=False, tracking=True)
    cycle_usage_count = fields.Integer(
        string='Cycle Usage Count', default=0, copy=False)
    last_maintenance_date = fields.Date(string='Last Maintenance Date', copy=False)
    maintenance_status = fields.Selection(
        MAINTENANCE_STATUS_SELECTION,
        string='Maintenance Status',
        compute='_compute_maintenance_status',
        store=True,
        index=True,
    )
    issued_user_id = fields.Many2one('res.users', string='Issued By')
    issued_date = fields.Datetime(string='Issued Date')
    disable_reason = fields.Char(string='Disable Reason')
    scrap_reason = fields.Char(string='Scrap Reason')
    state = fields.Selection(
        TOOL_STATE_SELECTION, string='Status', default='idle', required=True, index=True, tracking=True)
    record_ids = fields.One2many('sn.tooling.record', 'tooling_id', string='History')
    record_count = fields.Integer(compute='_compute_record_count')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_tooling_sn_unique = models.Constraint(
        'unique(company_id, sn)',
        'The tooling SN must be unique per company.',
    )

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        if name:
            domain = list(domain or []) + [
                '|', ('sn', operator, name), ('template_id.name', operator, name)]
            return super().name_search('', domain=domain, operator='ilike', limit=limit)
        return super().name_search(name, domain=domain, operator=operator, limit=limit)

    @api.depends(
        'cycle_usage_count',
        'template_id.maintenance_by_count',
        'template_id.maintenance_count_limit',
        'template_id.maintenance_count_reminder',
        'template_id.maintenance_by_cycle',
        'template_id.maintenance_cycle_days',
        'template_id.maintenance_cycle_reminder_days',
        'last_maintenance_date',
    )
    def _compute_maintenance_status(self):
        severity_rank = {'normal': 0, 'due': 1, 'expired': 2}
        today = fields.Date.context_today(self)
        for tooling in self:
            count_status = 'normal'
            cycle_status = 'normal'
            template = tooling.template_id
            if template.maintenance_by_count and template.maintenance_count_limit > 0:
                due_start = max(
                    template.maintenance_count_limit - template.maintenance_count_reminder, 0)
                if tooling.cycle_usage_count >= template.maintenance_count_limit:
                    count_status = 'expired'
                elif tooling.cycle_usage_count >= due_start:
                    count_status = 'due'
            if template.maintenance_by_cycle and template.maintenance_cycle_days > 0 \
                    and tooling.last_maintenance_date:
                due_date = tooling.last_maintenance_date + relativedelta(
                    days=template.maintenance_cycle_days)
                remind_date = due_date - relativedelta(
                    days=template.maintenance_cycle_reminder_days or 0)
                if today >= due_date:
                    cycle_status = 'expired'
                elif today >= remind_date:
                    cycle_status = 'due'
            tooling.maintenance_status = max(
                (count_status, cycle_status), key=lambda status: severity_rank[status])

    @api.depends('record_ids')
    def _compute_record_count(self):
        for tooling in self:
            tooling.record_count = len(tooling.record_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            template = self.env['sn.tooling.template'].browse(vals.get('template_id'))
            if template:
                # The web client submits untouched numeric fields as 0, so an
                # empty value also falls back to the template default.
                for param in ('tension', 'thickness', 'flatness'):
                    if not vals.get(param):
                        vals[param] = template[f'default_{param}']
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _ensure_not_expired(self):
        for tooling in self:
            if tooling.maintenance_status == 'expired':
                raise UserError(_(
                    'The tooling %s has expired maintenance. Maintain it first.',
                    tooling.sn))

    def _record(self, action, qty=False, fault=False, reason=False, line_vals=False):
        return self.env['sn.tooling.record'].create({
            'tooling_id': self.id,
            'action': action,
            'qty': qty,
            'fault': fault,
            'reason': reason,
            'line_ids': line_vals or [],
        })

    # ------------------------------------------------------------------
    # Lifecycle: issue / online / offline / return
    # ------------------------------------------------------------------

    def action_issue(self):
        for tooling in self:
            if tooling.state != 'idle':
                raise UserError(_('Only an idle tooling can be issued.'))
            tooling._ensure_not_expired()
            tooling.write({
                'state': 'issued',
                'issued_user_id': self.env.user.id,
                'issued_date': fields.Datetime.now(),
            })
            tooling._record('issue')
        return True

    def action_online(self):
        for tooling in self:
            if tooling.state != 'issued':
                raise UserError(_('Only an issued tooling can be put online.'))
            tooling._ensure_not_expired()
            tooling.write({'state': 'online'})
            tooling._record('online')
        return True

    def action_offline(self):
        for tooling in self:
            if tooling.state != 'online':
                raise UserError(_('Only an online tooling can be taken offline.'))
            tooling.write({'state': 'issued'})
            tooling._record('offline')
        return True

    def action_return(self):
        for tooling in self:
            if tooling.state != 'issued':
                raise UserError(_('Only an issued tooling can be returned.'))
            tooling.write({
                'state': 'idle',
                'issued_user_id': False,
                'issued_date': False,
            })
            tooling._record('return')
        return True

    # ------------------------------------------------------------------
    # Lifecycle: maintenance (two step)
    # ------------------------------------------------------------------

    def action_maintain_start(self):
        for tooling in self:
            if tooling.state != 'idle':
                raise UserError(_('Only an idle tooling can start maintenance.'))
            tooling.write({'state': 'maintaining'})
            tooling._record('maintain')
        return True

    def action_maintain_done(self, line_vals=False, params=False):
        today = fields.Date.context_today(self)
        for tooling in self:
            if tooling.state != 'maintaining':
                raise UserError(_('The tooling %s is not under maintenance.', tooling.sn))
            values = {
                'state': 'idle',
                'last_maintenance_date': today,
                'cycle_usage_count': 0,
            }
            params = params or {}
            for param in ('tension', 'thickness', 'flatness'):
                if params.get(param) is not None:
                    values[param] = params[param]
            tooling.write(values)
            tooling._record('maintain', line_vals=line_vals or [])
        return True

    # ------------------------------------------------------------------
    # Lifecycle: repair (two step, done may scrap)
    # ------------------------------------------------------------------

    def action_repair_start(self, fault):
        for tooling in self:
            if tooling.state != 'idle':
                raise UserError(_('Only an idle tooling can start repair.'))
            if not fault:
                raise UserError(_('A fault description is required to start repair.'))
            tooling.write({'state': 'repairing'})
            tooling._record('repair', fault=fault)
        return True

    def action_repair_done(self, outcome, reason=False):
        for tooling in self:
            if tooling.state != 'repairing':
                raise UserError(_('The tooling %s is not under repair.', tooling.sn))
            if outcome == 'scrap':
                if not reason:
                    raise UserError(_('A scrap reason is required to scrap the tooling.'))
                tooling.write({'state': 'scrapped', 'scrap_reason': reason})
            else:
                tooling.write({'state': 'idle'})
            tooling._record('repair', reason=reason or _('Repaired'))
        return True

    # ------------------------------------------------------------------
    # Lifecycle: disable / enable / scrap
    # ------------------------------------------------------------------

    def action_disable(self, reason=False):
        for tooling in self:
            if tooling.state != 'idle':
                raise UserError(_('Only an idle tooling can be disabled.'))
            if not reason:
                raise UserError(_('A disable reason is required.'))
            tooling.write({'state': 'disabled', 'disable_reason': reason})
            tooling._record('disable', reason=reason)
        return True

    def action_enable(self):
        for tooling in self:
            if tooling.state != 'disabled':
                raise UserError(_('Only a disabled tooling can be enabled.'))
            tooling.write({'state': 'idle', 'disable_reason': False})
            tooling._record('enable')
        return True

    def action_scrap(self, reason=False):
        for tooling in self:
            if tooling.state not in ('idle', 'disabled'):
                raise UserError(_(
                    'The tooling %s must be returned or its maintenance/repair finished before scrapping.',
                    tooling.sn))
            if not reason:
                raise UserError(_('A scrap reason is required.'))
            tooling.write({'state': 'scrapped', 'scrap_reason': reason})
            tooling._record('scrap', reason=reason)
        return True

    # ------------------------------------------------------------------
    # Usage counting (external modules drive it by SN)
    # ------------------------------------------------------------------

    def register_usage(self, qty):
        for tooling in self:
            if tooling.state != 'online':
                raise UserError(_(
                    'Only an online tooling can register usage (%s).', tooling.sn))
            if not isinstance(qty, int) or qty <= 0:
                raise UserError(_('The usage quantity must be a positive integer.'))
            tooling.write({
                'total_usage_count': tooling.total_usage_count + qty,
                'cycle_usage_count': tooling.cycle_usage_count + qty,
            })
            tooling._record('usage', qty=qty)
        return True

    def action_view_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tooling Records'),
            'res_model': 'sn.tooling.record',
            'view_mode': 'list,form',
            'domain': [('tooling_id', '=', self.id)],
            'context': {'default_tooling_id': self.id},
        }

    # ------------------------------------------------------------------
    # Wizards
    # ------------------------------------------------------------------

    def action_open_maintain_done(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.tooling.maintain.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': self.env.ref('sn_wsd_tooling.action_sn_tooling_maintain_wizard').name,
            'context': {'default_tooling_id': self.id},
        }

    def action_open_repair_start(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.tooling.repair.start.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': self.env.ref('sn_wsd_tooling.action_sn_tooling_repair_start_wizard').name,
            'context': {'default_tooling_id': self.id},
        }

    def action_open_repair_done(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.tooling.repair.done.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': self.env.ref('sn_wsd_tooling.action_sn_tooling_repair_done_wizard').name,
            'context': {'default_tooling_id': self.id},
        }

    def action_open_disable(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.tooling.disable.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': self.env.ref('sn_wsd_tooling.action_sn_tooling_disable_wizard').name,
            'context': {'default_tooling_id': self.id},
        }

    def action_open_scrap(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.tooling.scrap.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': self.env.ref('sn_wsd_tooling.action_sn_tooling_scrap_wizard').name,
            'context': {'default_tooling_id': self.id},
        }


class SnToolingRecord(models.Model):
    _name = 'sn.tooling.record'
    _description = 'Tooling Record'
    _order = 'tooling_id, id desc'
    _check_company_auto = True

    tooling_id = fields.Many2one(
        'sn.tooling',
        string='Tooling SN',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    template_id = fields.Many2one(
        'sn.tooling.template', related='tooling_id.template_id', store=True, index=True)
    action = fields.Selection(RECORD_ACTION_SELECTION, string='Action', required=True, index=True)
    qty = fields.Integer(string='Quantity')
    fault = fields.Char(string='Fault')
    reason = fields.Char(string='Reason')
    line_ids = fields.One2many('sn.tooling.record.line', 'record_id', string='Check Items')
    user_id = fields.Many2one(
        'res.users', string='User', default=lambda self: self.env.user, required=True)
    occurred_at = fields.Datetime(string='Occurred At', default=fields.Datetime.now, required=True)
    company_id = fields.Many2one(
        'res.company', related='tooling_id.company_id', store=True, index=True)


class SnToolingRecordLine(models.Model):
    _name = 'sn.tooling.record.line'
    _description = 'Tooling Record Line'
    _order = 'record_id, sequence, id'

    record_id = fields.Many2one(
        'sn.tooling.record', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Item Name', required=True)
    result = fields.Selection(
        MAINTENANCE_RESULT_SELECTION, string='Result', default='done', required=True)
    note = fields.Char(string='Note')
