from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SnWsdSerialFreeze(models.Model):
    _name = 'sn.wsd.serial.freeze'
    _description = 'SN Freeze Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'freeze_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Freeze Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Meter Serial',
        required=True,
        index=True,
        check_company=True,
        tracking=True,
    )
    serial_no = fields.Char(
        string='SN',
        related='serial_id.serial_no',
        store=True,
        readonly=True,
        index=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='serial_id.production_id',
        store=True,
        readonly=True,
        index=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='serial_id.mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Freeze Work Order',
        check_company=True,
        index=True,
        tracking=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Freeze Work Center',
        related='workorder_id.workcenter_id',
        store=True,
        readonly=True,
        index=True,
    )
    operation_id = fields.Many2one(
        'mrp.routing.workcenter',
        string='Freeze Operation',
        related='workorder_id.operation_id',
        store=True,
        readonly=True,
        index=True,
    )
    freeze_reason = fields.Text(string='Freeze Reason', required=True, tracking=True)
    freeze_user_id = fields.Many2one(
        'res.users',
        string='Freeze User',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    freeze_time = fields.Datetime(
        string='Freeze Time',
        required=True,
        default=fields.Datetime.now,
        tracking=True,
        index=True,
    )
    release_reason = fields.Text(string='Release Reason', tracking=True)
    release_user_id = fields.Many2one(
        'res.users',
        string='Release User',
        tracking=True,
    )
    release_time = fields.Datetime(
        string='Release Time',
        tracking=True,
        index=True,
    )
    state = fields.Selection(
        [
            ('frozen', 'Frozen'),
            ('released', 'Released'),
        ],
        string='Status',
        required=True,
        default='frozen',
        tracking=True,
        index=True,
    )
    note = fields.Text(string='Notes')

    @api.constrains('serial_id', 'state')
    def _check_single_active_freeze(self):
        for record in self.filtered(lambda item: item.state == 'frozen'):
            domain = [
                ('serial_id', '=', record.serial_id.id),
                ('state', '=', 'frozen'),
                ('id', '!=', record.id),
            ]
            if self.search_count(domain):
                raise ValidationError(_('Only one active freeze record is allowed for each SN.'))

    @api.constrains('serial_id', 'workorder_id')
    def _check_serial_can_be_frozen(self):
        for record in self.filtered(lambda item: item.state == 'frozen'):
            serial = record.serial_id
            if serial.final_result == 'scrap' or serial.pack_date:
                raise ValidationError(_('Finished or scrapped SNs cannot be frozen.'))
            if record.workorder_id and serial.production_id and record.workorder_id.production_id != serial.production_id:
                raise ValidationError(_('The freeze work order must belong to the same manufacturing order as the SN.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.serial.freeze') or _('New')
        records = super().create(vals_list)
        records._sync_serial_freeze_state()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._sync_serial_freeze_state()
        if {'state', 'serial_id'}.intersection(vals):
            self.mapped('serial_id')._sync_freeze_state()
        return result

    def unlink(self):
        serials = self.mapped('serial_id')
        result = super().unlink()
        serials._sync_freeze_state()
        return result

    def _sync_serial_freeze_state(self):
        self.mapped('serial_id')._sync_freeze_state()

    def action_release(self, release_reason=False):
        release_time = fields.Datetime.now()
        self.filtered(lambda record: record.state == 'frozen').write({
            'state': 'released',
            'release_reason': release_reason or False,
            'release_user_id': self.env.user.id,
            'release_time': release_time,
        })
        return True

    def action_open_release_wizard(self):
        records = self.filtered(lambda record: record.state == 'frozen')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Release Frozen SNs'),
            'res_model': 'sn.wsd.serial.freeze.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'sn.wsd.serial.freeze',
                'active_ids': records.ids,
                'default_mode': 'release',
            },
        }


class InternalSerial(models.Model):
    _inherit = 'sn.wsd.internal.serial'

    freeze_record_ids = fields.One2many(
        'sn.wsd.serial.freeze',
        'serial_id',
        string='Freeze Records',
        readonly=True,
    )
    active_freeze_id = fields.Many2one(
        'sn.wsd.serial.freeze',
        string='Active Freeze',
        compute='_compute_active_freeze_id',
        store=True,
    )
    freeze_count = fields.Integer(
        string='Freeze Count',
        compute='_compute_freeze_count',
    )
    x_freeze_state = fields.Selection(
        [
            ('normal', 'Normal'),
            ('frozen', 'Frozen'),
        ],
        string='Freeze State',
        default='normal',
        index=True,
    )
    freeze_reason = fields.Text(
        string='Current Freeze Reason',
        related='active_freeze_id.freeze_reason',
        readonly=True,
    )
    freeze_time = fields.Datetime(
        string='Current Freeze Time',
        related='active_freeze_id.freeze_time',
        readonly=True,
    )

    @api.depends('freeze_record_ids.state', 'freeze_record_ids.freeze_time')
    def _compute_active_freeze_id(self):
        for serial in self:
            frozen_records = serial.freeze_record_ids.filtered(lambda record: record.state == 'frozen')
            serial.active_freeze_id = frozen_records.sorted(lambda record: (record.freeze_time, record.id), reverse=True)[:1]

    @api.depends('freeze_record_ids')
    def _compute_freeze_count(self):
        for serial in self:
            serial.freeze_count = len(serial.freeze_record_ids)

    def _sync_freeze_state(self):
        for serial in self:
            frozen = bool(serial.freeze_record_ids.filtered(lambda record: record.state == 'frozen'))
            values = {'x_freeze_state': 'frozen' if frozen else 'normal'}
            if frozen:
                values['x_quality_hold_state'] = 'blocked'
            elif serial.x_quality_hold_state == 'blocked':
                open_issues = getattr(serial, 'quality_issue_ids', self.env['sn.wsd.quality.issue']).filtered(
                    lambda issue: issue.state not in ('closed', 'scrapped')
                )
                values['x_quality_hold_state'] = 'hold' if open_issues else 'released'
            serial.write(values)

    def action_open_freeze_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SN Freeze Records'),
            'res_model': 'sn.wsd.serial.freeze',
            'view_mode': 'list,form',
            'domain': [('serial_id', '=', self.id)],
            'context': {
                'default_serial_id': self.id,
                'default_workorder_id': self.current_workorder_id.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_open_freeze_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Freeze SN'),
            'res_model': 'sn.wsd.serial.freeze.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_mode': 'single',
                'default_serial_id': self.id,
                'default_workorder_id': self.current_workorder_id.id,
            },
        }


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    x_freeze_record_ids = fields.One2many(
        'sn.wsd.serial.freeze',
        'workorder_id',
        string='Freeze Records',
        readonly=True,
    )
    x_freeze_record_count = fields.Integer(
        string='Freeze Record Count',
        compute='_compute_x_freeze_record_count',
    )

    def _compute_x_freeze_record_count(self):
        for workorder in self:
            workorder.x_freeze_record_count = len(workorder.x_freeze_record_ids)

    def _get_freezable_internal_serials(self):
        self.ensure_one()
        return self.env['sn.wsd.internal.serial'].search([
            ('production_id', '=', self.production_id.id),
            ('current_workorder_id', '=', self.id),
            ('final_result', '!=', 'scrap'),
            ('pack_date', '=', False),
            ('x_freeze_state', '!=', 'frozen'),
        ])

    def action_open_freeze_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Freeze Work Order SNs'),
            'res_model': 'sn.wsd.serial.freeze.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_mode': 'workorder',
                'default_production_id': self.production_id.id,
                'default_workorder_id': self.id,
            },
        }

    def _mes_validate_execution(self, serial_number=None, allow_restart=False, override_route=False):
        result = super()._mes_validate_execution(
            serial_number=serial_number,
            allow_restart=allow_restart,
            override_route=override_route,
        )
        if result.get('error') or not serial_number:
            return result
        serial = self.env['sn.wsd.internal.serial'].search([
            ('serial_no', '=', serial_number),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        active_freeze = serial.active_freeze_id if serial else self.env['sn.wsd.serial.freeze']
        if not active_freeze:
            return result
        api = self.env['sncic.mes.api.mixin']
        return api._mes_error(
            'serial_frozen',
            message=_(
                'SN %(serial)s is frozen. Reason: %(reason)s. Passing is not allowed.',
                serial=serial_number,
                reason=active_freeze.freeze_reason or '-',
            ),
            serial_number=serial_number,
            freeze_id=active_freeze.id,
            freeze_reason=active_freeze.freeze_reason,
            freeze_user=active_freeze.freeze_user_id.display_name,
            freeze_time=active_freeze.freeze_time,
            freeze_workorder_id=active_freeze.workorder_id.id,
        )
