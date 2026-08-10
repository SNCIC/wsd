from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


PLAN_TYPE_SELECTION = [
    ('maintenance', 'Maintenance'),
    ('inspection', 'Inspection'),
    ('calibration', 'Calibration'),
]

EXECUTION_STATE_SELECTION = [
    ('draft', 'Draft'),
    ('submitted', 'Submitted'),
    ('reviewed', 'Reviewed'),
    ('done', 'Done'),
    ('skipped', 'Skipped'),
    ('cancel', 'Cancelled'),
]

RESULT_SELECTION = [
    ('ok', 'OK'),
    ('ng', 'NG'),
    ('na', 'N/A'),
]


class SnWsdMaintenanceItem(models.Model):
    _name = 'sn.wsd.maintenance.item'
    _description = 'Maintenance and Inspection Item'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'item_type, code, id'
    _check_company_auto = True

    name = fields.Char(string='Item Name', required=True, tracking=True)
    code = fields.Char(string='Item Code', required=True, tracking=True, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    item_type = fields.Selection([
        ('maintenance', 'Maintenance Item'),
        ('inspection', 'Inspection Item'),
        ('calibration', 'Calibration Item'),
    ], string='Item Type', required=True, default='maintenance', tracking=True)
    check_content = fields.Text(string='Work Content', required=True)
    standard = fields.Text(string='Standard')
    check_method = fields.Selection([
        ('visual', 'Visual'),
        ('measurement', 'Measurement'),
        ('function', 'Functional Test'),
    ], string='Check Method', default='visual', required=True)
    uom = fields.Char(string='Unit')
    lower_limit = fields.Float(string='Lower Limit')
    upper_limit = fields.Float(string='Upper Limit')
    required = fields.Boolean(string='Required', default=True)
    category_ids = fields.Many2many(
        'maintenance.equipment.category',
        'sn_wsd_maintenance_item_category_rel',
        'item_id',
        'category_id',
        string='Applicable Categories',
    )
    plan_line_ids = fields.One2many('sn.wsd.maintenance.plan.item', 'item_id', string='Plan Lines')

    _sn_wsd_maintenance_item_code_unique = models.Constraint(
        'unique(code, company_id)',
        'The maintenance item code must be unique per company.',
    )

    @api.constrains('lower_limit', 'upper_limit')
    def _check_limits(self):
        for item in self:
            if item.lower_limit and item.upper_limit and item.lower_limit > item.upper_limit:
                raise ValidationError(_('Lower limit cannot be greater than upper limit.'))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_referenced_by_plan(self):
        for item in self:
            if item.plan_line_ids:
                raise UserError(_('A maintenance item referenced by a plan cannot be deleted. Archive it instead.'))


class SnWsdMaintenancePlan(models.Model):
    _name = 'sn.wsd.maintenance.plan'
    _description = 'Equipment Maintenance Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'plan_type, equipment_id, category_id, id'
    _check_company_auto = True

    name = fields.Char(
        string='Plan Number',
        required=True,
        default='/',
        copy=False,
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    plan_type = fields.Selection(
        PLAN_TYPE_SELECTION,
        string='Plan Type',
        required=True,
        default='maintenance',
        tracking=True,
    )
    equipment_id = fields.Many2one(
        'maintenance.equipment',
        string='Equipment',
        check_company=True,
        tracking=True,
    )
    category_id = fields.Many2one(
        'maintenance.equipment.category',
        string='Equipment Category',
        check_company=True,
        tracking=True,
    )
    maintenance_category = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ], string='Maintenance Category', tracking=True)
    inspection_frequency = fields.Selection([
        ('shift', 'Every Shift'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
    ], string='Inspection Frequency', tracking=True)
    shift_code = fields.Char(string='Shift')
    cycle_days = fields.Integer(string='Cycle Days', default=1, tracking=True)
    reminder_days = fields.Integer(string='Reminder Days', default=0, tracking=True)
    baseline_hours = fields.Float(string='Baseline Hours')
    responsible_user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        tracking=True,
    )
    responsible_department_id = fields.Many2one('hr.department', string='Responsible Department', tracking=True)
    standard_equipment_id = fields.Many2one(
        'maintenance.equipment',
        string='Reference Standard',
        check_company=True,
    )
    calibration_basis = fields.Char(string='Calibration Basis')
    next_date = fields.Date(
        string='Next Due Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    last_execution_date = fields.Date(string='Last Execution Date', readonly=True)
    line_ids = fields.One2many(
        'sn.wsd.maintenance.plan.item',
        'plan_id',
        string='Items',
    )
    execution_ids = fields.One2many(
        'sn.wsd.maintenance.execution',
        'plan_id',
        string='Executions',
    )
    execution_count = fields.Integer(compute='_compute_execution_count')

    _sn_wsd_plan_name_unique = models.Constraint(
        'unique(name, company_id)',
        'The maintenance plan number must be unique per company.',
    )

    @api.depends('execution_ids')
    def _compute_execution_count(self):
        for plan in self:
            plan.execution_count = len(plan.execution_ids)

    @api.constrains('equipment_id', 'category_id', 'cycle_days', 'reminder_days',
                    'plan_type', 'maintenance_category', 'inspection_frequency', 'calibration_basis', 'line_ids')
    def _check_plan_config(self):
        for plan in self:
            if not plan.equipment_id and not plan.category_id:
                raise ValidationError(_('Either equipment or equipment category is required.'))
            if plan.cycle_days <= 0:
                raise ValidationError(_('Cycle days must be greater than zero.'))
            if plan.reminder_days < 0:
                raise ValidationError(_('Reminder days cannot be negative.'))
            if plan.plan_type == 'maintenance' and not plan.maintenance_category:
                raise ValidationError(_('Maintenance category is required for maintenance plans.'))
            if plan.plan_type == 'inspection' and not plan.inspection_frequency:
                raise ValidationError(_('Inspection frequency is required for inspection plans.'))
            if plan.plan_type == 'calibration' and not plan.calibration_basis:
                raise ValidationError(_('Calibration basis is required for calibration plans.'))
            if not plan.line_ids:
                raise ValidationError(_('At least one plan item is required.'))

    @api.onchange('equipment_id')
    def _onchange_equipment_id(self):
        for plan in self:
            if plan.equipment_id:
                plan.company_id = plan.equipment_id.company_id
                plan.category_id = plan.equipment_id.category_id
                plan.responsible_user_id = (
                    plan.equipment_id.technician_user_id or plan.equipment_id.owner_user_id
                )

    @api.onchange('category_id', 'plan_type')
    def _onchange_category_id_load_default_items(self):
        for plan in self:
            if not plan.category_id or plan.line_ids:
                continue
            item_type = 'maintenance' if plan.plan_type == 'maintenance' else plan.plan_type
            default_items = plan.category_id.default_item_ids.filtered(
                lambda item: item.item_type == item_type
            )
            plan.line_ids = [
                fields.Command.create({
                    'sequence': index * 10,
                    'item_id': item.id,
                    'required': item.required,
                })
                for index, item in enumerate(default_items, start=1)
            ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.maintenance.plan') or '/'
        return super().create(vals_list)

    def _target_equipment(self):
        self.ensure_one()
        if self.equipment_id:
            return self.equipment_id
        return self.env['maintenance.equipment'].search([
            ('category_id', '=', self.category_id.id),
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ])

    def action_generate_execution(self):
        execution_model = self.env['sn.wsd.maintenance.execution']
        created = execution_model
        for plan in self:
            for equipment in plan._target_equipment():
                execution = execution_model.create(plan._prepare_execution_values(equipment))
                created |= execution
        if len(created) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Maintenance Execution'),
                'res_model': 'sn.wsd.maintenance.execution',
                'view_mode': 'form',
                'res_id': created.id,
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Executions'),
            'res_model': 'sn.wsd.maintenance.execution',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }

    def _prepare_execution_values(self, equipment):
        self.ensure_one()
        return {
            'plan_id': self.id,
            'execution_type': self.plan_type,
            'equipment_id': equipment.id,
            'workcenter_id': equipment.x_mes_workcenter_id.id if equipment.x_mes_workcenter_id else False,
            'planned_date': self.next_date,
            'responsible_user_id': self.responsible_user_id.id,
            'baseline_hours': self.baseline_hours,
            'line_ids': [
                fields.Command.create({
                    'sequence': line.sequence,
                    'item_id': line.item_id.id,
                    'required': line.required,
                    'standard': line.item_id.standard,
                })
                for line in self.line_ids
            ],
        }

    def _advance_next_date(self, execution_date=False):
        target_date = execution_date or fields.Date.context_today(self)
        for plan in self:
            plan.write({
                'last_execution_date': target_date,
                'next_date': target_date + relativedelta(days=plan.cycle_days),
            })

    @api.model
    def cron_generate_due_executions(self):
        today = fields.Date.context_today(self)
        plans = self.search([('active', '=', True)])
        for plan in plans:
            reminder_date = plan.next_date - relativedelta(days=plan.reminder_days or 0)
            if reminder_date > today:
                continue
            target_equipment = plan._target_equipment()
            for equipment in target_equipment:
                existing = self.env['sn.wsd.maintenance.execution'].search_count([
                    ('plan_id', '=', plan.id),
                    ('equipment_id', '=', equipment.id),
                    ('state', 'in', ['draft', 'submitted', 'reviewed']),
                ], limit=1)
                if existing:
                    continue
                self.env['sn.wsd.maintenance.execution'].create(
                    plan._prepare_execution_values(equipment)
                )
                if plan.plan_type == 'inspection' and plan.next_date < today:
                    equipment.x_equipment_state = 'inspection_due'

    @api.model
    def cron_update_calibration_alerts(self):
        today = fields.Date.context_today(self)
        overdue_equipment = self.env['maintenance.equipment'].search([
            ('x_requires_calibration', '=', True),
            ('x_next_calibration_date', '!=', False),
            ('x_next_calibration_date', '<', today),
            ('x_equipment_state', 'not in', ['scrapped', 'calibration_overdue']),
        ])
        overdue_equipment.write({'x_equipment_state': 'calibration_overdue'})


class SnWsdMaintenancePlanItem(models.Model):
    _name = 'sn.wsd.maintenance.plan.item'
    _description = 'Maintenance Plan Item'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    plan_id = fields.Many2one('sn.wsd.maintenance.plan', required=True, ondelete='cascade')
    item_id = fields.Many2one('sn.wsd.maintenance.item', required=True, ondelete='restrict')
    required = fields.Boolean(default=True)
    note = fields.Char(string='Note')


class SnWsdMaintenanceExecution(models.Model):
    _name = 'sn.wsd.maintenance.execution'
    _description = 'Equipment Maintenance Execution'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'planned_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Execution Number',
        required=True,
        default='/',
        copy=False,
        tracking=True,
    )
    company_id = fields.Many2one(related='equipment_id.company_id', store=True)
    plan_id = fields.Many2one('sn.wsd.maintenance.plan', string='Plan', check_company=True)
    execution_type = fields.Selection(
        PLAN_TYPE_SELECTION,
        string='Execution Type',
        required=True,
        default='maintenance',
        tracking=True,
    )
    equipment_id = fields.Many2one(
        'maintenance.equipment',
        string='Equipment',
        required=True,
        check_company=True,
        tracking=True,
    )
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', check_company=True)
    planned_date = fields.Date(
        string='Planned Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    start_time = fields.Datetime(string='Start Time', tracking=True)
    end_time = fields.Datetime(string='End Time', tracking=True)
    actual_hours = fields.Float(string='Actual Hours', compute='_compute_actual_hours', store=True)
    baseline_hours = fields.Float(string='Baseline Hours')
    responsible_user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        tracking=True,
    )
    reviewer_id = fields.Many2one('res.users', string='Reviewer', tracking=True)
    review_time = fields.Datetime(string='Review Time', tracking=True)
    state = fields.Selection(
        EXECUTION_STATE_SELECTION,
        string='State',
        default='draft',
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        'sn.wsd.maintenance.execution.line',
        'execution_id',
        string='Execution Lines',
    )
    abnormal_count = fields.Integer(compute='_compute_abnormal_count', store=True)
    note = fields.Text(string='Note')
    skip_reason = fields.Text(string='Skip Reason')
    authorized_user_id = fields.Many2one('res.users', string='Authorized By')
    certificate = fields.Binary(string='Certificate')
    certificate_filename = fields.Char(string='Certificate Filename')
    calibration_before = fields.Char(string='Before Calibration')
    calibration_after = fields.Char(string='After Calibration')
    calibration_deviation = fields.Char(string='Deviation')
    calibration_adjustment = fields.Text(string='Adjustment')
    calibration_result = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('downgraded', 'Downgraded Use'),
    ], string='Calibration Result')
    next_calibration_date = fields.Date(string='Next Calibration Date')
    maintenance_request_id = fields.Many2one(
        'maintenance.request',
        string='Failure Request',
        check_company=True,
    )

    @api.depends('start_time', 'end_time')
    def _compute_actual_hours(self):
        for execution in self:
            if execution.start_time and execution.end_time:
                execution.actual_hours = (execution.end_time - execution.start_time).total_seconds() / 3600
            else:
                execution.actual_hours = 0.0

    @api.depends('line_ids.result')
    def _compute_abnormal_count(self):
        for execution in self:
            execution.abnormal_count = len(execution.line_ids.filtered(lambda line: line.result == 'ng'))

    @api.constrains('start_time', 'end_time')
    def _check_dates(self):
        for execution in self:
            if execution.start_time and execution.end_time and execution.start_time > execution.end_time:
                raise ValidationError(_('End time cannot be earlier than start time.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.maintenance.execution') or '/'
        return super().create(vals_list)

    def action_start(self):
        self.write({'state': 'draft', 'start_time': fields.Datetime.now()})

    def action_submit(self):
        for execution in self:
            missing_lines = execution.line_ids.filtered(lambda line: line.required and not line.result)
            if missing_lines:
                raise UserError(_('Required maintenance items must be recorded before submit.'))
            abnormal_without_note = execution.line_ids.filtered(
                lambda line: line.result == 'ng' and not line.abnormal_note
            )
            if abnormal_without_note:
                raise UserError(_('Abnormal lines require an abnormal description.'))
            if execution.execution_type == 'calibration':
                if execution.calibration_result == 'pass' and execution.equipment_id.x_calibration_type == 'external' and not execution.certificate:
                    raise UserError(_('External calibration requires a certificate.'))
                if not execution.calibration_result:
                    raise UserError(_('Calibration result is required.'))
        self.write({'state': 'submitted', 'end_time': fields.Datetime.now()})
        self.filtered(lambda item: item.abnormal_count)._create_failure_request_from_abnormal()

    def action_review(self):
        self.write({
            'state': 'reviewed',
            'reviewer_id': self.env.user.id,
            'review_time': fields.Datetime.now(),
        })

    def action_done(self):
        for execution in self:
            if execution.state not in ('submitted', 'reviewed'):
                raise UserError(_('Only submitted or reviewed executions can be completed.'))
            if execution.execution_type == 'calibration' and execution.calibration_result == 'fail':
                execution.equipment_id.x_equipment_state = 'stopped'
            elif execution.execution_type == 'inspection' and execution.abnormal_count:
                execution.equipment_id.x_equipment_state = 'inspection_due'
            elif not execution.abnormal_count:
                execution.equipment_id.x_equipment_state = 'running'
            if execution.execution_type == 'calibration' and execution.calibration_result in ('pass', 'downgraded'):
                execution.equipment_id.write({
                    'x_last_calibration_date': fields.Date.context_today(self),
                })
            execution.plan_id._advance_next_date(fields.Date.context_today(self))
            execution.equipment_id._create_lifecycle_log(
                execution.execution_type,
                _('Execution %s completed.') % execution.name,
                source_model=execution._name,
                source_id=execution.id,
            )
        self.write({'state': 'done'})

    def action_skip(self):
        for execution in self:
            if not execution.skip_reason or not execution.authorized_user_id:
                raise UserError(_('Skip reason and authorized user are required.'))
        self.write({'state': 'skipped'})

    def action_create_failure_request(self):
        self.ensure_one()
        self._create_failure_request_from_abnormal()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Failure Request'),
            'res_model': 'maintenance.request',
            'view_mode': 'form',
            'res_id': self.maintenance_request_id.id,
        }

    def _create_failure_request_from_abnormal(self):
        request_model = self.env['maintenance.request']
        for execution in self.filtered(lambda item: item.equipment_id and not item.maintenance_request_id):
            request = request_model.create({
                'name': _('Abnormal equipment execution %s') % execution.name,
                'equipment_id': execution.equipment_id.id,
                'maintenance_type': 'corrective',
                'x_failure_code': execution.execution_type,
                'x_failure_time': fields.Datetime.now(),
                'x_impact_level': 'reduced_output',
                'x_urgency': 'normal',
                'description': execution.note or _('Created from abnormal maintenance execution.'),
            })
            execution.maintenance_request_id = request
            execution.equipment_id.x_equipment_state = 'repairing'


class SnWsdMaintenanceExecutionLine(models.Model):
    _name = 'sn.wsd.maintenance.execution.line'
    _description = 'Maintenance Execution Line'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    execution_id = fields.Many2one(
        'sn.wsd.maintenance.execution',
        required=True,
        ondelete='cascade',
    )
    item_id = fields.Many2one(
        'sn.wsd.maintenance.item',
        required=True,
        ondelete='restrict',
    )
    required = fields.Boolean(default=True)
    standard = fields.Text(string='Standard')
    result = fields.Selection(RESULT_SELECTION, string='Result')
    measured_value = fields.Float(string='Measured Value')
    abnormal_note = fields.Text(string='Abnormal Note')
    spare_part_note = fields.Text(string='Spare Part Note')


class SnWsdMaintenanceDowntime(models.Model):
    _name = 'sn.wsd.maintenance.downtime'
    _description = 'Equipment Downtime Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Downtime Number',
        required=True,
        default='/',
        copy=False,
    )
    company_id = fields.Many2one(related='equipment_id.company_id', store=True)
    equipment_id = fields.Many2one(
        'maintenance.equipment',
        required=True,
        check_company=True,
        tracking=True,
    )
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', check_company=True)
    maintenance_request_id = fields.Many2one(
        'maintenance.request',
        string='Maintenance Request',
        check_company=True,
    )
    failure_code = fields.Char(string='Failure Code')
    reason = fields.Text(string='Reason', required=True)
    start_time = fields.Datetime(
        string='Start Time',
        required=True,
        default=fields.Datetime.now,
        tracking=True,
    )
    end_time = fields.Datetime(string='End Time', tracking=True)
    duration_hours = fields.Float(
        string='Duration Hours',
        compute='_compute_duration_hours',
        store=True,
    )
    state = fields.Selection(
        [('open', 'Open'), ('closed', 'Closed')],
        default='open',
        required=True,
        tracking=True,
    )

    @api.depends('start_time', 'end_time')
    def _compute_duration_hours(self):
        for downtime in self:
            end_time = downtime.end_time or fields.Datetime.now()
            downtime.duration_hours = (
                (end_time - downtime.start_time).total_seconds() / 3600
                if downtime.start_time else 0.0
            )

    @api.constrains('start_time', 'end_time')
    def _check_dates(self):
        for downtime in self:
            if downtime.start_time and downtime.end_time and downtime.start_time > downtime.end_time:
                raise ValidationError(_('Downtime end cannot be earlier than start time.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped('equipment_id').write({'x_equipment_state': 'stopped'})
        for record in records:
            record.equipment_id._create_lifecycle_log(
                'downtime',
                _('Downtime %s opened.') % record.name,
                source_model=record._name,
                source_id=record.id,
            )
        return records

    def action_close(self):
        self.write({'state': 'closed', 'end_time': fields.Datetime.now()})
        for downtime in self:
            downtime.equipment_id._create_lifecycle_log(
                'downtime',
                _('Downtime %s closed.') % downtime.name,
                source_model=downtime._name,
                source_id=downtime.id,
            )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_never(self):
        raise UserError(_('Downtime records cannot be deleted.'))
