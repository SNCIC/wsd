from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

REPAIR_TYPE_SELECTION = [
    ('false_alarm', 'False Alarm Check'),
    ('onsite', 'On-site Repair'),
    ('outsourced', 'Outsourced Repair'),
    ('return_factory', 'Return to Factory Repair'),
]


class RepairOrder(models.Model):
    """Equipment repair order: full loop from fault report to completion."""
    _name = 'sn.wsd.device.repair.order'
    _description = 'Equipment Repair Order'
    _order = 'fault_time desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Repair Reference', default='/', copy=False,
        readonly=True, index=True)
    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment',
        required=True, index=True, ondelete='restrict')
    equipment_code = fields.Char(
        related='equipment_id.code', store=True, string='Equipment Code')
    equipment_name = fields.Char(
        related='equipment_id.name', store=True, string='Equipment Name')
    company_id = fields.Many2one(
        related='equipment_id.company_id', store=True,
        string='Company', index=True)

    # ===== fault report =====
    fault_phenomenon = fields.Html(string='Fault Phenomenon', required=True)
    initial_handling = fields.Html(string='Initial Handling', required=True)
    is_downtime = fields.Boolean(string='Downtime')
    fault_type = fields.Selection(
        selection=[
            ('mechanical', 'Mechanical Fault'),
            ('electrical', 'Electrical Fault'),
            ('software', 'Software Fault'),
            ('other', 'Other Fault'),
        ], string='Fault Type', required=True, index=True)
    fault_level = fields.Selection(
        selection=[
            ('minor', 'Minor'),
            ('general', 'General'),
            ('critical', 'Critical'),
        ], string='Fault Level', required=True, index=True)
    fault_time = fields.Datetime(
        string='Fault Time', required=True, readonly=True, index=True,
        default=fields.Datetime.now)
    reported_user_id = fields.Many2one(
        'res.users', string='Reported By', readonly=True,
        default=lambda self: self.env.user, index=True)
    responsible_user_id = fields.Many2one(
        'res.users', string='Repair Responsible', index=True)
    state = fields.Selection(
        selection=[
            ('pending', 'Pending Acceptance'),
            ('repairing', 'Repairing'),
            ('done', 'Done'),
        ], string='Status', required=True, default='pending',
        index=True, copy=False)

    # ===== acceptance =====
    accept_user_id = fields.Many2one(
        'res.users', string='Accepted By', readonly=True, copy=False)
    accept_time = fields.Datetime(
        string='Accept Time', readonly=True, copy=False)
    accept_duration_hours = fields.Float(
        string='Accept Duration (h)', compute='_compute_accept_duration_hours',
        store=True, digits=(10, 2),
        help='Elapsed time between the fault time and the accept time.')

    # ===== repair records and completion =====
    record_ids = fields.One2many(
        'sn.wsd.device.repair.record', 'repair_order_id',
        string='Repair Records')
    record_count = fields.Integer(
        string='Repair Record Count', compute='_compute_record_count')
    repair_user_id = fields.Many2one(
        'res.users', string='Repair User', readonly=True, copy=False)
    repair_time = fields.Datetime(
        string='Repair Time', readonly=True, copy=False)
    completion_time = fields.Datetime(
        string='Completion Time', readonly=True, copy=False)
    repair_duration_hours = fields.Float(
        string='Repair Duration (h)', compute='_compute_repair_duration_hours',
        store=True, digits=(10, 2),
        help='Elapsed time between the fault time and the completion time.')

    @api.depends('accept_time', 'fault_time')
    def _compute_accept_duration_hours(self):
        for order in self:
            if order.accept_time and order.fault_time:
                delta = order.accept_time - order.fault_time
                order.accept_duration_hours = \
                    max(delta.total_seconds(), 0.0) / 3600
            else:
                order.accept_duration_hours = 0.0

    @api.depends('completion_time', 'fault_time')
    def _compute_repair_duration_hours(self):
        for order in self:
            if order.completion_time and order.fault_time:
                delta = order.completion_time - order.fault_time
                order.repair_duration_hours = \
                    max(delta.total_seconds(), 0.0) / 3600
            else:
                order.repair_duration_hours = 0.0

    def _compute_record_count(self):
        groups = self.env['sn.wsd.device.repair.record']._read_group(
            [('repair_order_id', 'in', self.ids)],
            ['repair_order_id'], ['__count'])
        counts = {order.id: count for order, count in groups}
        for order in self:
            order.record_count = counts.get(order.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.device.repair.order') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('allow_repair_order_write'):
            protected = set(vals) - {
                'message_follower_ids', 'activity_ids'}
            if protected and any(order.state == 'done' for order in self):
                raise UserError(_('Completed repair orders cannot be modified.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        if self.env.context.get('allow_repair_order_write'):
            return
        if any(order.state == 'done' for order in self):
            raise UserError(_('Completed repair orders cannot be deleted.'))

    def _ensure_acceptable(self):
        for order in self:
            if order.state != 'pending':
                raise UserError(_('Only pending repair orders can be accepted.'))

    def _ensure_repairable(self):
        for order in self:
            if order.state != 'repairing':
                raise UserError(
                    _('Only repairing orders can record repairs.'))

    def action_accept(self):
        """Accept the order: anyone may accept, timestamps are automatic."""
        self._ensure_acceptable()
        now = fields.Datetime.now()
        self.with_context(allow_repair_order_write=True).write({
            'state': 'repairing',
            'accept_user_id': self.env.user.id,
            'accept_time': now,
        })
        return True

    def action_complete(self):
        """Complete the order and close the loop on the equipment ledger."""
        for order in self:
            if order.state != 'repairing':
                raise UserError(
                    _('Only repairing orders can be completed.'))
            now = fields.Datetime.now()
            order.with_context(allow_repair_order_write=True).write({
                'state': 'done',
                'completion_time': now,
                'repair_user_id': self.env.user.id,
                'repair_time': now,
            })
            order.equipment_id.last_repair_date = now
        return True

    def action_view_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Repair Order'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_accept_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Accept Repair Order'),
            'res_model': 'sn.wsd.device.repair.accept.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_repair_order_id': self.id},
        }

    def action_open_record_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record Repair'),
            'res_model': 'sn.wsd.device.repair.record.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_repair_order_id': self.id},
        }


class RepairRecord(models.Model):
    """One repair intervention logged on a repair order (may be many)."""
    _name = 'sn.wsd.device.repair.record'
    _description = 'Equipment Repair Record'
    _order = 'record_time, id'
    _rec_name = 'display_name'

    repair_order_id = fields.Many2one(
        'sn.wsd.device.repair.order', string='Repair Order',
        required=True, index=True, ondelete='cascade')
    repair_type = fields.Selection(
        selection=REPAIR_TYPE_SELECTION, string='Repair Type',
        required=True, index=True)
    investigation_process = fields.Html(
        string='Investigation Process')
    repair_process = fields.Html(string='Repair Process')
    vendor_company = fields.Char(string='Outsourced Company')
    contact_person = fields.Char(string='Contact Person')
    contact_phone = fields.Char(string='Contact Phone')
    expected_completion_time = fields.Datetime(
        string='Expected Completion Time')
    repair_user_id = fields.Many2one(
        'res.users', string='Repair User', readonly=True,
        default=lambda self: self.env.user, index=True)
    record_time = fields.Datetime(
        string='Record Time', required=True, readonly=True,
        default=fields.Datetime.now, index=True)

    @api.depends('repair_type', 'repair_user_id.name', 'record_time')
    def _compute_display_name(self):
        for record in self:
            record.display_name = _(
                '%(type)s by %(user)s at %(time)s',
                type=record.repair_type and dict(
                    record._fields['repair_type']
                    ._description_selection(record.env)
                ).get(record.repair_type) or '',
                user=record.repair_user_id.name or '',
                time=record.record_time or '')

    @api.constrains('repair_type', 'investigation_process', 'repair_process',
                    'contact_person', 'contact_phone',
                    'expected_completion_time')
    def _check_required_by_type(self):
        for record in self:
            if record.repair_type == 'false_alarm' \
                    and not record.investigation_process:
                raise ValidationError(_(
                    'The investigation process is required for a false '
                    'alarm check.'))
            if record.repair_type == 'onsite' and not record.repair_process:
                raise ValidationError(_(
                    'The repair process is required for an on-site repair.'))
            if record.repair_type in ('outsourced', 'return_factory'):
                if not record.contact_person or not record.contact_phone:
                    raise ValidationError(_(
                        'Contact person and phone are required for '
                        'outsourced and return-to-factory repairs.'))
                if not record.expected_completion_time:
                    raise ValidationError(_(
                        'The expected completion time is required for '
                        'outsourced and return-to-factory repairs.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Mirror the last recorded intervention on the order (R8/R9).
        orders = records.mapped('repair_order_id')
        for order in orders:
            last = order.record_ids[-1:]
            if last:
                order.with_context(allow_repair_order_write=True).write({
                    'repair_user_id': last.repair_user_id.id,
                    'repair_time': last.record_time,
                })
        return records
