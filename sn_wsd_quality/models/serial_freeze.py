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
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity',
        string='SN',
        required=True,
        index=True,
        check_company=True,
        tracking=True,
        ondelete='restrict',
    )
    serial_no = fields.Char(
        string='SN',
        related='serial_identity_id.name',
        store=True,
        readonly=True,
        index=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Freeze Route Operation',
        check_company=True,
        index=True,
        tracking=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='route_operation_id.mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='mes_order_id.production_id',
        store=True,
        readonly=True,
        index=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Freeze Work Center',
        compute='_compute_route_context',
        store=True,
        readonly=True,
        index=True,
    )
    operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='MES Operation',
        compute='_compute_route_context',
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

    @api.depends('route_operation_id', 'route_operation_id.operation_id')
    def _compute_route_context(self):
        for record in self:
            operation = record.route_operation_id.operation_id
            record.operation_id = operation
            record.workcenter_id = operation.x_workcenter_ids[:1] if operation else False

    @api.constrains('serial_identity_id', 'state')
    def _check_single_active_freeze(self):
        for record in self.filtered(lambda item: item.state == 'frozen'):
            domain = [
                ('serial_identity_id', '=', record.serial_identity_id.id),
                ('state', '=', 'frozen'),
                ('id', '!=', record.id),
            ]
            if self.search_count(domain):
                raise ValidationError(_('Only one active freeze record is allowed for each SN.'))

    @api.constrains('serial_identity_id', 'route_operation_id')
    def _check_serial_can_be_frozen(self):
        ScrapRecord = self.env['sn.wsd.scrap.record']
        PackRecord = self.env['sn.wsd.meter.pack.record']
        Wip = self.env['sn.wsd.serial.wip']
        for record in self.filtered(lambda item: item.state == 'frozen'):
            identity = record.serial_identity_id
            if ScrapRecord.search_count([
                    ('serial_identity_id', '=', identity.id),
                    ('state', '=', 'scrapped')]):
                raise ValidationError(_('Scrapped SNs cannot be frozen.'))
            if PackRecord.search_count([('serial_identity_id', '=', identity.id)]):
                raise ValidationError(_('Packed SNs cannot be frozen.'))
            wip = Wip.search([('serial_identity_id', '=', identity.id)], limit=1)
            if record.route_operation_id and wip and \
                    record.route_operation_id.mes_order_id != wip.mes_order_id:
                raise ValidationError(_(
                    'The freeze route operation must belong to the same MES '
                    'order as the SN.'))

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
        if {'state', 'serial_identity_id'}.intersection(vals):
            self.mapped('serial_identity_id')._sync_freeze_state()
        return result

    def unlink(self):
        identities = self.mapped('serial_identity_id')
        result = super().unlink()
        identities._sync_freeze_state()
        return result

    def _sync_serial_freeze_state(self):
        self.mapped('serial_identity_id')._sync_freeze_state()

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


class SerialIdentity(models.Model):
    _inherit = 'sn.wsd.serial.identity'

    freeze_record_ids = fields.One2many(
        'sn.wsd.serial.freeze',
        'serial_identity_id',
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
        for identity in self:
            frozen_records = identity.freeze_record_ids.filtered(lambda record: record.state == 'frozen')
            identity.active_freeze_id = frozen_records.sorted(
                lambda record: (record.freeze_time, record.id), reverse=True)[:1]

    @api.depends('freeze_record_ids')
    def _compute_freeze_count(self):
        for identity in self:
            identity.freeze_count = len(identity.freeze_record_ids)

    def _sync_freeze_state(self):
        for identity in self:
            frozen = bool(identity.freeze_record_ids.filtered(lambda record: record.state == 'frozen'))
            values = {'x_freeze_state': 'frozen' if frozen else 'normal'}
            if frozen:
                values['x_quality_hold_state'] = 'blocked'
            elif identity.x_quality_hold_state == 'blocked':
                open_issues = identity.quality_issue_ids.filtered(
                    lambda issue: issue.state not in ('closed', 'scrapped')
                )
                values['x_quality_hold_state'] = 'hold' if open_issues else 'released'
            identity.write(values)

    def _current_route_operation(self):
        """The route operation the SN currently sits at (WIP first, then
        the latest history row)."""
        self.ensure_one()
        wip = self.env['sn.wsd.serial.wip'].search(
            [('serial_identity_id', '=', self.id)], limit=1)
        if wip:
            return wip.route_operation_id
        history = self.env['sn.wsd.serial.operation.history'].search(
            [('serial_identity_id', '=', self.id)],
            order='out_date desc, id desc', limit=1)
        return history.route_operation_id

    def action_open_freeze_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SN Freeze Records'),
            'res_model': 'sn.wsd.serial.freeze',
            'view_mode': 'list,form',
            'domain': [('serial_identity_id', '=', self.id)],
            'context': {
                'default_serial_identity_id': self.id,
                'default_route_operation_id': self._current_route_operation().id,
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
                'default_serial_identity_id': self.id,
                'default_route_operation_id': self._current_route_operation().id,
            },
        }
