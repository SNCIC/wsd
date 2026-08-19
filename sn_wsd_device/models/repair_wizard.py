from odoo import _, api, fields, models

from .repair_order import REPAIR_TYPE_SELECTION


class RepairCreateWizard(models.TransientModel):
    """Dialog used by operators to report a new equipment fault."""
    _name = 'sn.wsd.device.repair.create.wizard'
    _description = 'Equipment Repair Report'

    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Fault Equipment', required=True)
    equipment_code = fields.Char(
        related='equipment_id.code', string='Equipment Code', readonly=True)
    equipment_name = fields.Char(
        related='equipment_id.name', string='Equipment Name', readonly=True)
    responsible_user_id = fields.Many2one(
        'res.users', string='Repair Responsible',
        help='Defaults to the equipment maintenance responsible and may '
             'be reselected.')
    fault_phenomenon = fields.Html(string='Fault Phenomenon', required=True)
    initial_handling = fields.Html(string='Initial Handling', required=True)
    is_downtime = fields.Boolean(string='Downtime')
    fault_type = fields.Selection(
        selection=[
            ('mechanical', 'Mechanical Fault'),
            ('electrical', 'Electrical Fault'),
            ('software', 'Software Fault'),
            ('other', 'Other Fault'),
        ], string='Fault Type', required=True)
    fault_level = fields.Selection(
        selection=[
            ('minor', 'Minor'),
            ('general', 'General'),
            ('critical', 'Critical'),
        ], string='Fault Level', required=True)
    fault_time = fields.Datetime(
        string='Fault Time', required=True, readonly=True,
        default=fields.Datetime.now)

    @api.onchange('equipment_id')
    def _onchange_equipment_id(self):
        if self.equipment_id:
            self.responsible_user_id = \
                self.equipment_id.maintenance_user_id

    def action_submit(self):
        self.ensure_one()
        self.env['sn.wsd.device.repair.order'].create({
            'equipment_id': self.equipment_id.id,
            'responsible_user_id': self.responsible_user_id.id,
            'fault_phenomenon': self.fault_phenomenon,
            'initial_handling': self.initial_handling,
            'is_downtime': self.is_downtime,
            'fault_type': self.fault_type,
            'fault_level': self.fault_level,
            'fault_time': self.fault_time,
            'reported_user_id': self.env.user.id,
        })
        return {'type': 'ir.actions.act_window_close'}


class RepairAcceptWizard(models.TransientModel):
    """Read-only report summary shown before accepting a repair order."""
    _name = 'sn.wsd.device.repair.accept.wizard'
    _description = 'Equipment Repair Acceptance'

    repair_order_id = fields.Many2one(
        'sn.wsd.device.repair.order', string='Repair Order', required=True)
    equipment_id = fields.Many2one(
        related='repair_order_id.equipment_id', string='Equipment',
        readonly=True)
    equipment_code = fields.Char(
        related='repair_order_id.equipment_code', string='Equipment Code',
        readonly=True)
    equipment_name = fields.Char(
        related='repair_order_id.equipment_name', string='Equipment Name',
        readonly=True)
    responsible_user_id = fields.Many2one(
        related='repair_order_id.responsible_user_id',
        string='Repair Responsible', readonly=True)
    fault_phenomenon = fields.Html(
        related='repair_order_id.fault_phenomenon',
        string='Fault Phenomenon', readonly=True)
    initial_handling = fields.Html(
        related='repair_order_id.initial_handling',
        string='Initial Handling', readonly=True)
    is_downtime = fields.Boolean(
        related='repair_order_id.is_downtime', string='Downtime',
        readonly=True)
    fault_type = fields.Selection(
        related='repair_order_id.fault_type', string='Fault Type',
        readonly=True)
    fault_level = fields.Selection(
        related='repair_order_id.fault_level', string='Fault Level',
        readonly=True)
    fault_time = fields.Datetime(
        related='repair_order_id.fault_time', string='Fault Time',
        readonly=True)
    reported_user_id = fields.Many2one(
        related='repair_order_id.reported_user_id', string='Reported By',
        readonly=True)

    def action_confirm(self):
        self.ensure_one()
        self.repair_order_id.action_accept()
        return {'type': 'ir.actions.act_window_close'}


class RepairRecordWizard(models.TransientModel):
    """Dialog to log one repair intervention, optionally completing the
    order in the same step."""
    _name = 'sn.wsd.device.repair.record.wizard'
    _description = 'Equipment Repair Record'

    repair_order_id = fields.Many2one(
        'sn.wsd.device.repair.order', string='Repair Order', required=True)
    equipment_code = fields.Char(
        related='repair_order_id.equipment_code', string='Equipment Code',
        readonly=True)
    equipment_name = fields.Char(
        related='repair_order_id.equipment_name', string='Equipment Name',
        readonly=True)
    repair_type = fields.Selection(
        selection=REPAIR_TYPE_SELECTION, string='Repair Type', required=True)
    investigation_process = fields.Html(string='Investigation Process')
    repair_process = fields.Html(string='Repair Process')
    vendor_company = fields.Char(string='Outsourced Company')
    contact_person = fields.Char(string='Contact Person')
    contact_phone = fields.Char(string='Contact Phone')
    expected_completion_time = fields.Datetime(
        string='Expected Completion Time')
    repair_user_id = fields.Many2one(
        'res.users', string='Repair User', readonly=True,
        default=lambda self: self.env.user)
    record_time = fields.Datetime(
        string='Record Time', required=True, readonly=True,
        default=fields.Datetime.now)

    def _prepare_record_vals(self):
        self.ensure_one()
        return {
            'repair_order_id': self.repair_order_id.id,
            'repair_type': self.repair_type,
            'investigation_process': self.investigation_process,
            'repair_process': self.repair_process,
            'vendor_company': self.vendor_company,
            'contact_person': self.contact_person,
            'contact_phone': self.contact_phone,
            'expected_completion_time': self.expected_completion_time,
            'repair_user_id': self.repair_user_id.id,
            'record_time': self.record_time,
        }

    def action_save_record(self):
        self.ensure_one()
        self.repair_order_id._ensure_repairable()
        self.env['sn.wsd.device.repair.record'].create(
            self._prepare_record_vals())
        return {'type': 'ir.actions.act_window_close'}

    def action_complete_repair(self):
        self.ensure_one()
        self.repair_order_id._ensure_repairable()
        self.env['sn.wsd.device.repair.record'].create(
            self._prepare_record_vals())
        self.repair_order_id.action_complete()
        return {'type': 'ir.actions.act_window_close'}
