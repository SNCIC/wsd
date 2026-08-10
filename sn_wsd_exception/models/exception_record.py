from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SnWsdExceptionRecord(models.Model):
    _name = 'sn.wsd.exception.record'
    _description = 'SN WSD Exception Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'occurred_at desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Exception Reference',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    exception_type_id = fields.Many2one(
        'sn.wsd.exception.type',
        string='Exception Type',
        required=True,
        check_company=True,
        tracking=True,
        index=True,
    )
    category = fields.Selection(
        related='exception_type_id.category',
        string='Category',
        store=True,
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('to_verify', 'To Verify'),
            ('closed', 'Closed'),
            ('suspended', 'Suspended'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        required=True,
        default='pending',
        tracking=True,
        index=True,
    )
    description = fields.Text(string='Exception Description', required=True, tracking=True)
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'sn_wsd_exception_record_attachment_rel',
        'exception_id',
        'attachment_id',
        string='Site Photos',
        copy=False,
    )
    occurred_at = fields.Datetime(
        string='Occurred At',
        required=True,
        default=fields.Datetime.now,
        tracking=True,
        index=True,
    )
    reported_by_id = fields.Many2one(
        'res.users',
        string='Reported By',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    responsible_user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        tracking=True,
    )
    handler_user_id = fields.Many2one(
        'res.users',
        string='Handled By',
        tracking=True,
    )
    verifier_user_id = fields.Many2one(
        'res.users',
        string='Verified By',
        tracking=True,
    )
    escalation_user_id = fields.Many2one(
        'res.users',
        string='Escalated To',
        readonly=True,
        tracking=True,
    )
    closed_by_id = fields.Many2one(
        'res.users',
        string='Closed By',
        readonly=True,
        tracking=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        check_company=True,
        index=True,
        tracking=True,
    )
    manufacturing_batch_id = fields.Many2one(
        'sn.wsd.manufacturing.batch',
        string='Manufacturing Batch',
        check_company=True,
        index=True,
        tracking=True,
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        check_company=True,
        index=True,
        tracking=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        check_company=True,
        index=True,
    )
    route_step_id = fields.Many2one(
        'sn.wsd.process.route.operation',
        string='Process Step',
        check_company=True,
        index=True,
    )
    equipment_id = fields.Many2one(
        'maintenance.equipment',
        string='Equipment',
        check_company=True,
        index=True,
        tracking=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Meter Serial',
        check_company=True,
        index=True,
        tracking=True,
    )
    serial_lot_id = fields.Many2one(
        'stock.lot',
        string='SN/Lot',
        check_company=True,
        index=True,
        tracking=True,
    )
    material_product_id = fields.Many2one(
        'product.product',
        string='Material',
        check_company=True,
        index=True,
        tracking=True,
    )
    root_cause = fields.Text(string='Root Cause Analysis', tracking=True)
    handling_plan = fields.Text(string='Handling Plan', tracking=True)
    handled_result = fields.Text(string='Handling Result', tracking=True)
    verification_note = fields.Text(string='Verification Note', tracking=True)
    verification_result = fields.Selection(
        [('ok', 'OK'), ('ng', 'NG')],
        string='Verification Result',
        tracking=True,
    )
    processing_started_at = fields.Datetime(string='Processing Started At', readonly=True, tracking=True)
    handled_at = fields.Datetime(string='Handled At', readonly=True, tracking=True)
    verified_at = fields.Datetime(string='Verified At', readonly=True, tracking=True)
    escalated_at = fields.Datetime(string='Escalated At', readonly=True, tracking=True)
    suspended_at = fields.Datetime(string='Suspended At', readonly=True, tracking=True)
    closed_at = fields.Datetime(string='Closed At', readonly=True, tracking=True)
    is_overdue = fields.Boolean(string='Overdue', compute='_compute_exception_flags', search='_search_is_overdue')
    can_close = fields.Boolean(string='Can Close', compute='_compute_exception_flags')

    @api.depends('state', 'exception_type_id.timeout_minutes', 'occurred_at', 'verification_result')
    def _compute_exception_flags(self):
        now = fields.Datetime.now()
        for record in self:
            timeout = record.exception_type_id.timeout_minutes or 0
            deadline = record.occurred_at + timedelta(minutes=timeout) if record.occurred_at and timeout else False
            record.is_overdue = bool(deadline and record.state in ('pending', 'in_progress') and now > deadline)
            record.can_close = record.state == 'to_verify' and record.verification_result == 'ok'

    @api.model
    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(_('Unsupported operator for overdue search.'))
        now = fields.Datetime.now()
        overdue_ids = []
        records = self.search([('state', 'in', ['pending', 'in_progress'])])
        for record in records:
            timeout = record.exception_type_id.timeout_minutes or 0
            if timeout and record.occurred_at and record.occurred_at + timedelta(minutes=timeout) < now:
                overdue_ids.append(record.id)
        is_positive = (operator == '=' and value) or (operator == '!=' and not value)
        return [('id', 'in' if is_positive else 'not in', overdue_ids)]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.exception.record') or _('New')
        records = super().create(vals_list)
        records._sync_context_from_links()
        records._notify_registration()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'workorder_id', 'internal_serial_id', 'serial_lot_id', 'equipment_id'}.intersection(vals):
            self._sync_context_from_links()
        return result

    @api.onchange('workorder_id')
    def _onchange_workorder_id(self):
        for record in self:
            if not record.workorder_id:
                continue
            record.production_id = record.workorder_id.production_id
            record.manufacturing_batch_id = record.workorder_id.x_manufacturing_batch_id
            record.workcenter_id = record.workorder_id.workcenter_id
            record.route_step_id = record.workorder_id.x_route_operation_id
            record.equipment_id = record.workorder_id.x_meter_equipment_id

    @api.onchange('internal_serial_id')
    def _onchange_internal_serial_id(self):
        for record in self:
            serial = record.internal_serial_id
            if not serial:
                continue
            record.serial_lot_id = False
            record.production_id = record.production_id or serial.production_id
            record.manufacturing_batch_id = record.manufacturing_batch_id or serial.manufacturing_batch_id
            record.workorder_id = record.workorder_id or serial.current_workorder_id

    @api.onchange('serial_lot_id')
    def _onchange_serial_lot_id(self):
        for record in self:
            serial = record.serial_lot_id
            if serial:
                record.internal_serial_id = self.env['sn.wsd.internal.serial'].search([
                    ('serial_no', '=', serial.name),
                    ('company_id', '=', record.company_id.id),
                ], limit=1)

    def _sync_context_from_links(self):
        for record in self:
            vals = {}
            if record.workorder_id:
                if not record.production_id:
                    vals['production_id'] = record.workorder_id.production_id.id
                if not record.manufacturing_batch_id and record.workorder_id.x_manufacturing_batch_id:
                    vals['manufacturing_batch_id'] = record.workorder_id.x_manufacturing_batch_id.id
                if not record.workcenter_id:
                    vals['workcenter_id'] = record.workorder_id.workcenter_id.id
                if not record.route_step_id and record.workorder_id.x_route_operation_id:
                    vals['route_step_id'] = record.workorder_id.x_route_operation_id.id
                if not record.equipment_id and record.workorder_id.x_meter_equipment_id:
                    vals['equipment_id'] = record.workorder_id.x_meter_equipment_id.id
            if record.internal_serial_id:
                if record.serial_lot_id:
                    vals['serial_lot_id'] = False
                if not record.production_id:
                    vals['production_id'] = record.internal_serial_id.production_id.id
                if not record.manufacturing_batch_id and record.internal_serial_id.manufacturing_batch_id:
                    vals['manufacturing_batch_id'] = record.internal_serial_id.manufacturing_batch_id.id
                if not record.workorder_id:
                    vals['workorder_id'] = record.internal_serial_id.current_workorder_id.id
            if record.serial_lot_id and not record.internal_serial_id:
                serial = self.env['sn.wsd.internal.serial'].search([
                    ('serial_no', '=', record.serial_lot_id.name),
                    ('company_id', '=', record.company_id.id),
                ], limit=1)
                if serial:
                    vals['internal_serial_id'] = serial.id
            if vals:
                record.with_context(skip_exception_sync=True).write(vals)

    def _users_from_groups(self, groups):
        users = self.env['res.users']
        for group in groups:
            users |= group.users
        return users.filtered(lambda user: user.active and user.partner_id)

    def _schedule_activity_for_users(self, users, summary, note):
        activity_type = self.env.ref('mail.mail_activity_data_todo')
        for record in self:
            for user in users:
                record.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=user.id,
                    summary=summary,
                    note=note,
                )

    def _notify_registration(self):
        for record in self:
            users = record._users_from_groups(record.exception_type_id.notify_group_ids)
            if record.responsible_user_id:
                users |= record.responsible_user_id
            if users:
                record._schedule_activity_for_users(
                    users,
                    _('New MES exception: %s') % record.name,
                    record.description,
                )
            record.message_post(body=_('Exception was registered.'))

    def _check_mutable_state(self):
        if any(record.state in ('closed', 'cancelled') for record in self):
            raise UserError(_('Closed or cancelled exceptions cannot be changed by this action.'))

    def action_start_processing(self):
        for record in self:
            if record.state not in ('pending', 'suspended'):
                raise UserError(_('Only pending or suspended exceptions can be started.'))
            record.write({
                'state': 'in_progress',
                'handler_user_id': self.env.user.id,
                'processing_started_at': fields.Datetime.now(),
            })
            record.message_post(body=_('Exception processing started.'))
        return True

    def action_submit_to_verify(self):
        for record in self:
            if record.state != 'in_progress':
                raise UserError(_('Only in-progress exceptions can be submitted for verification.'))
            if not record.root_cause or not record.handling_plan or not record.handled_result:
                raise ValidationError(_('Root cause, handling plan, and handling result are required before verification.'))
            record.write({
                'state': 'to_verify',
                'handler_user_id': record.handler_user_id.id or self.env.user.id,
                'handled_at': fields.Datetime.now(),
            })
            if record.verifier_user_id:
                record._schedule_activity_for_users(
                    record.verifier_user_id,
                    _('Verify MES exception: %s') % record.name,
                    record.handled_result,
                )
            record.message_post(body=_('Exception was submitted for verification.'))
        return True

    def action_verify_ok(self):
        for record in self:
            if record.state != 'to_verify':
                raise UserError(_('Only exceptions waiting for verification can be verified.'))
            record.write({
                'verification_result': 'ok',
                'verifier_user_id': record.verifier_user_id.id or self.env.user.id,
                'verified_at': fields.Datetime.now(),
            })
            record.message_post(body=_('Exception verification passed.'))
        return True

    def action_verify_ng(self):
        for record in self:
            if record.state != 'to_verify':
                raise UserError(_('Only exceptions waiting for verification can be rejected.'))
            record.write({
                'state': 'in_progress',
                'verification_result': 'ng',
                'verifier_user_id': record.verifier_user_id.id or self.env.user.id,
                'verified_at': fields.Datetime.now(),
            })
            record.message_post(body=_('Exception verification failed and was returned for processing.'))
        return True

    def action_close(self):
        for record in self:
            if record.state != 'to_verify' or record.verification_result != 'ok':
                raise UserError(_('Only verified OK exceptions can be closed.'))
            record.write({
                'state': 'closed',
                'closed_by_id': self.env.user.id,
                'closed_at': fields.Datetime.now(),
            })
            record.message_post(body=_('Exception was closed.'))
        return True

    def action_suspend(self):
        for record in self:
            if record.state in ('closed', 'cancelled'):
                raise UserError(_('Closed or cancelled exceptions cannot be suspended.'))
            record.write({
                'state': 'suspended',
                'suspended_at': fields.Datetime.now(),
            })
            record.message_post(body=_('Exception was suspended.'))
        return True

    def action_cancel(self):
        for record in self:
            if record.state == 'closed':
                raise UserError(_('Closed exceptions cannot be cancelled.'))
            record.write({'state': 'cancelled'})
            record.message_post(body=_('Exception was cancelled.'))
        return True

    @api.model
    def cron_escalate_overdue_exceptions(self):
        now = fields.Datetime.now()
        records = self.search([('state', 'in', ['pending', 'in_progress'])])
        for record in records:
            timeout = record.exception_type_id.timeout_minutes or 0
            if not timeout or not record.occurred_at:
                continue
            if record.occurred_at + timedelta(minutes=timeout) >= now:
                continue
            users = record._users_from_groups(record.exception_type_id.escalation_group_ids)
            escalation_user = users[:1]
            vals = {'escalated_at': record.escalated_at or now}
            if escalation_user and not record.escalation_user_id:
                vals['escalation_user_id'] = escalation_user.id
            record.write(vals)
            if users:
                record._schedule_activity_for_users(
                    users,
                    _('Escalated MES exception: %s') % record.name,
                    record.description,
                )
            record.message_post(body=_('Exception was escalated because it was overdue.'))

            suspend_minutes = record.exception_type_id.suspend_after_escalation_minutes or 0
            if suspend_minutes and record.escalated_at and record.escalated_at + timedelta(minutes=suspend_minutes) < now:
                record.action_suspend()
