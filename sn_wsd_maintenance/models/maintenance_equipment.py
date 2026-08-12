from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


EQUIPMENT_STATE_SELECTION = [
    ('running', 'Running'),
    ('standby', 'Standby'),
    ('stopped', 'Stopped'),
    ('repairing', 'Under Repair'),
    ('inspection_due', 'Inspection Due'),
    ('calibration_overdue', 'Calibration Overdue'),
    ('scrapped', 'Scrapped'),
]

class MaintenanceEquipmentCategory(models.Model):
    _inherit = 'maintenance.equipment.category'

    active = fields.Boolean(default=True)
    code = fields.Char(string='Category Code', copy=False, index=True)
    parent_id = fields.Many2one(
        'maintenance.equipment.category',
        string='Parent Category',
        check_company=True,
        ondelete='restrict',
    )
    child_ids = fields.One2many(
        'maintenance.equipment.category',
        'parent_id',
        string='Child Categories',
    )
    default_item_ids = fields.Many2many(
        'sn.wsd.maintenance.item',
        'sn_wsd_maintenance_category_item_rel',
        'category_id',
        'item_id',
        string='Default Maintenance Items',
    )
    complete_name = fields.Char(compute='_compute_complete_name', store=True, recursive=True)

    _sn_wsd_category_code_unique = models.Constraint(
        'unique(code, company_id)',
        'The equipment category code must be unique per company.',
    )

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            category.complete_name = (
                f'{category.parent_id.complete_name} / {category.name}'
                if category.parent_id
                else category.name
            )

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if not self._check_recursion():
            raise ValidationError(_('Recursive equipment categories are not allowed.'))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_referenced_by_maintenance_master_data(self):
        for category in self:
            if category.equipment_ids or category.child_ids:
                raise UserError(_('A referenced equipment category cannot be deleted. Archive it instead.'))


class MaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    x_wsd_equipment_code = fields.Char(
        string='Equipment Code', copy=False, readonly=True, tracking=True, index=True)
    x_manufacturer_id = fields.Many2one(
        'res.partner', string='Manufacturer', check_company=True, tracking=True)
    x_factory_serial_no = fields.Char(string='Factory Serial Number', copy=False, tracking=True)
    x_manufacture_date = fields.Date(string='Manufacture Date', tracking=True)
    x_commission_date = fields.Date(string='Commission Date', tracking=True)
    x_department_id = fields.Many2one('hr.department', string='Using Department', tracking=True)
    x_production_line_id = fields.Many2one(
        'sn.mrp.production.line',
        string='Production Line',
        check_company=True,
        tracking=True,
    )
    x_mes_workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Bound Work Center',
        check_company=True,
        tracking=True,
    )
    x_equipment_state = fields.Selection(
        EQUIPMENT_STATE_SELECTION,
        string='Equipment State',
        default='standby',
        required=True,
        tracking=True,
        index=True,
    )
    x_image = fields.Image(string='Equipment Image', max_width=1920, max_height=1920)
    x_technical_document = fields.Binary(string='Technical Document')
    x_technical_document_filename = fields.Char(string='Technical Document Filename')
    x_smt_device_loadpoint_ids = fields.One2many(
        'sn.smt.device.loadpoint',
        'device_id',
        string='SMT Loadpoints',
    )
    x_requires_calibration = fields.Boolean(string='Requires Calibration', tracking=True)
    x_calibration_type = fields.Selection([
        ('internal', 'Internal Calibration'),
        ('external', 'External Calibration'),
    ], string='Calibration Type', tracking=True)
    x_calibration_cycle_days = fields.Integer(string='Calibration Cycle Days', default=365, tracking=True)
    x_calibration_reminder_days = fields.Integer(string='Calibration Reminder Days', default=30, tracking=True)
    x_last_calibration_date = fields.Date(string='Last Calibration Date', tracking=True)
    x_next_calibration_date = fields.Date(
        string='Next Calibration Date',
        compute='_compute_x_next_calibration_date',
        store=True,
    )
    x_criticality = fields.Selection([
        ('a', 'A - Critical'),
        ('b', 'B - Important'),
        ('c', 'C - Normal'),
    ], string='Criticality', default='c', required=True, tracking=True)
    x_lifecycle_log_ids = fields.One2many(
        'sn.wsd.maintenance.lifecycle.log', 'equipment_id', string='Lifecycle Logs')
    x_maintenance_plan_ids = fields.One2many(
        'sn.wsd.maintenance.plan', 'equipment_id', string='Maintenance Plans')
    x_maintenance_execution_ids = fields.One2many(
        'sn.wsd.maintenance.execution', 'equipment_id', string='Maintenance Executions')
    x_downtime_ids = fields.One2many(
        'sn.wsd.maintenance.downtime', 'equipment_id', string='Downtime Records')
    x_downtime_count = fields.Integer(compute='_compute_x_wsd_counts', string='Downtime Count')
    x_execution_count = fields.Integer(compute='_compute_x_wsd_counts', string='Execution Count')
    x_open_downtime_count = fields.Integer(compute='_compute_x_wsd_counts', string='Open Downtime Count')
    _sn_wsd_equipment_code_unique = models.Constraint(
        'unique(x_wsd_equipment_code)',
        'Equipment code already exists.',
    )

    @api.depends('x_downtime_ids.state', 'x_maintenance_execution_ids.state')
    def _compute_x_wsd_counts(self):
        for equipment in self:
            equipment.x_downtime_count = len(equipment.x_downtime_ids)
            equipment.x_execution_count = len(equipment.x_maintenance_execution_ids)
            equipment.x_open_downtime_count = len(
                equipment.x_downtime_ids.filtered(lambda item: item.state == 'open'))

    @api.depends('x_requires_calibration', 'x_last_calibration_date', 'x_calibration_cycle_days')
    def _compute_x_next_calibration_date(self):
        for equipment in self:
            if equipment.x_requires_calibration and equipment.x_last_calibration_date and equipment.x_calibration_cycle_days:
                equipment.x_next_calibration_date = (
                    equipment.x_last_calibration_date + relativedelta(days=equipment.x_calibration_cycle_days)
                )
            else:
                equipment.x_next_calibration_date = False

    @api.constrains('x_requires_calibration', 'x_calibration_type', 'x_calibration_cycle_days', 'x_calibration_reminder_days')
    def _check_calibration_config(self):
        for equipment in self:
            if equipment.x_requires_calibration and not equipment.x_calibration_type:
                raise ValidationError(_('Calibration type is required when calibration is enabled.'))
            if equipment.x_requires_calibration and equipment.x_calibration_cycle_days <= 0:
                raise ValidationError(_('Calibration cycle days must be greater than zero.'))
            if equipment.x_calibration_reminder_days < 0:
                raise ValidationError(_('Calibration reminder days cannot be negative.'))

    @api.onchange('x_mes_workcenter_id')
    def _onchange_x_mes_workcenter_id(self):
        for equipment in self:
            if equipment.x_mes_workcenter_id:
                equipment.x_production_line_id = equipment.x_mes_workcenter_id.x_production_line_id
                if equipment.x_mes_workcenter_id.company_id:
                    equipment.company_id = equipment.x_mes_workcenter_id.company_id

    @api.onchange('x_production_line_id')
    def _onchange_x_production_line_id(self):
        for equipment in self:
            if equipment.x_production_line_id and equipment.company_id != equipment.x_production_line_id.company_id:
                equipment.company_id = equipment.x_production_line_id.company_id
            if equipment.x_mes_workcenter_id and equipment.x_mes_workcenter_id.x_production_line_id != equipment.x_production_line_id:
                equipment.x_mes_workcenter_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('x_wsd_equipment_code'):
                vals['x_wsd_equipment_code'] = self._next_equipment_code(vals)
        records = super().create(vals_list)
        records._create_lifecycle_log('acceptance', _('Equipment record created.'))
        return records

    def write(self, vals):
        if 'x_wsd_equipment_code' in vals:
            for equipment in self:
                if equipment.x_wsd_equipment_code and vals['x_wsd_equipment_code'] != equipment.x_wsd_equipment_code:
                    raise UserError(_('Equipment code cannot be changed after creation.'))
        previous_states = {equipment.id: equipment.x_equipment_state for equipment in self}
        result = super().write(vals)
        if 'x_equipment_state' in vals:
            for equipment in self:
                if previous_states.get(equipment.id) != equipment.x_equipment_state:
                    state_label = dict(EQUIPMENT_STATE_SELECTION).get(equipment.x_equipment_state)
                    equipment._create_lifecycle_log(
                        'state_change',
                        _('Equipment state changed to %s.') % state_label
                    )
                    if equipment.x_equipment_state == 'scrapped':
                        equipment._sync_scrapped_state()
        return result

    def _sync_scrapped_state(self):
        self.ensure_one()
        if self.active:
            self.with_context(skip_lifecycle_log=True).write({
                'active': False,
                'scrap_date': fields.Date.context_today(self),
            })

    def _next_equipment_code(self, vals):
        category = self.env['maintenance.equipment.category'].browse(vals.get('category_id'))
        prefix = (category.code or 'EQ').upper() if category else 'EQ'
        sequence = self.env['ir.sequence'].next_by_code('sn.wsd.maintenance.equipment') or '00001'
        return f'{prefix}-{sequence}'

    def _create_lifecycle_log(self, event_type, note=False, source_model=False, source_id=False):
        if self.env.context.get('skip_lifecycle_log'):
            return
        log_model = self.env['sn.wsd.maintenance.lifecycle.log'].sudo()
        for equipment in self:
            log_model.create({
                'equipment_id': equipment.id,
                'event_type': event_type,
                'event_time': fields.Datetime.now(),
                'user_id': self.env.user.id,
                'source_model': source_model,
                'source_id': source_id,
                'note': note,
            })

    def action_set_running(self):
        self.write({'x_equipment_state': 'running'})

    def action_set_standby(self):
        self.write({'x_equipment_state': 'standby'})

    def action_set_stopped(self):
        self.write({'x_equipment_state': 'stopped'})

    def action_scrap_wsd_equipment(self):
        self.write({'x_equipment_state': 'scrapped'})

    def action_open_wsd_executions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Executions'),
            'res_model': 'sn.wsd.maintenance.execution',
            'view_mode': 'list,form',
            'domain': [('equipment_id', '=', self.id)],
            'context': {'default_equipment_id': self.id},
        }

    def action_open_wsd_downtime(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Downtime Records'),
            'res_model': 'sn.wsd.maintenance.downtime',
            'view_mode': 'list,form',
            'domain': [('equipment_id', '=', self.id)],
            'context': {'default_equipment_id': self.id},
        }


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    x_smt_is_feeder_control = fields.Boolean(string='Feeder Control')
    x_smt_device_ids = fields.One2many(
        'sn.smt.workcenter.device',
        'workcenter_id',
        string='SMT Devices',
    )


class SnSmtDeviceLoadpoint(models.Model):
    _name = 'sn.smt.device.loadpoint'
    _description = 'SMT Device Loadpoint'
    _order = 'device_id, table_no, loadpoint, id'
    _check_company_auto = True

    device_id = fields.Many2one(
        'maintenance.equipment',
        string='Device',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='device_id.company_id',
        store=True,
        readonly=True,
    )
    cd_device_sn = fields.Char(related='device_id.serial_no', string='CD_DEVICE_SN', store=True, readonly=True)
    track_type = fields.Selection(
        [('single', 'Single Track'), ('dual', 'Dual Track')],
        string='Track',
        default='single',
        required=True,
    )
    table_no = fields.Char(string='Table', required=True)
    loadpoint = fields.Char(string='Material Station', required=True)
    note = fields.Char(string='Description')

    _sn_smt_device_loadpoint_unique = models.Constraint(
        'unique(device_id, track_type, table_no, loadpoint)',
        'The table and material station must be unique per device and track.',
    )


class SnSmtWorkcenterDevice(models.Model):
    _name = 'sn.smt.workcenter.device'
    _description = 'SMT Workcenter Device Sequence'
    _order = 'workcenter_id, device_seq, id'
    _check_company_auto = True

    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='workcenter_id.company_id',
        store=True,
        readonly=True,
    )
    device_id = fields.Many2one(
        'maintenance.equipment',
        string='Device',
        required=True,
        ondelete='restrict',
        check_company=True,
    )
    device_seq = fields.Integer(string='Device Sequence', required=True)
    track_type = fields.Selection(
        [('single', 'Single Track'), ('dual', 'Dual Track')],
        string='Track Type',
        default='single',
        required=True,
    )
    note = fields.Char(string='Note')
    # 设备关联信息（只读，从所选设备自动带入）
    device_sn = fields.Char(
        related='device_id.serial_no',
        string='Device SN',
        store=True,
    )
    device_name = fields.Char(
        related='device_id.name',
        string='Device Name',
    )
    device_category_id = fields.Many2one(
        'maintenance.equipment.category',
        related='device_id.category_id',
        string='Device Category',
        store=True,
    )

    _sn_smt_workcenter_device_seq_unique = models.Constraint(
        'unique(workcenter_id, device_seq)',
        'The device sequence must be unique per work center.',
    )
    _sn_smt_workcenter_device_unique = models.Constraint(
        'unique(workcenter_id, device_id)',
        'A device can only be linked once to the same work center.',
    )


class SnWsdMaintenanceLifecycleLog(models.Model):
    _name = 'sn.wsd.maintenance.lifecycle.log'
    _description = 'Equipment Lifecycle Log'
    _order = 'event_time desc, id desc'
    _check_company_auto = True

    equipment_id = fields.Many2one(
        'maintenance.equipment',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(related='equipment_id.company_id', store=True)
    event_type = fields.Selection([
        ('acceptance', 'Acceptance'),
        ('maintenance', 'Maintenance'),
        ('inspection', 'Inspection'),
        ('repair', 'Repair'),
        ('calibration', 'Calibration'),
        ('downtime', 'Downtime'),
        ('state_change', 'State Change'),
        ('scrap', 'Scrap'),
    ], string='Event Type', required=True, index=True)
    event_time = fields.Datetime(required=True, default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    source_model = fields.Char(string='Source Model')
    source_id = fields.Integer(string='Source ID')
    note = fields.Text(string='Note')

    @api.ondelete(at_uninstall=False)
    def _unlink_except_never(self):
        raise UserError(_('Equipment lifecycle logs cannot be deleted.'))
