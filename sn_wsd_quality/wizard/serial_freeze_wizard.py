from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SnWsdSerialFreezeWizard(models.TransientModel):
    _name = 'sn.wsd.serial.freeze.wizard'
    _description = 'SN Freeze Wizard'

    mode = fields.Selection(
        [
            ('single', 'Single SN Freeze'),
            ('route_operation', 'Route Operation Batch Freeze'),
            ('release', 'Batch Release'),
        ],
        required=True,
        default='single',
    )
    serial_no = fields.Char(string='SN')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity',
        string='SN',
        check_company=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        check_company=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Route Operation',
        check_company=True,
    )
    freeze_reason = fields.Text(string='Freeze Reason')
    release_reason = fields.Text(string='Release Reason')
    freeze_record_ids = fields.Many2many(
        'sn.wsd.serial.freeze',
        string='Freeze Records',
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or []
        if active_model == 'sn.wsd.serial.freeze' and active_ids:
            records = self.env['sn.wsd.serial.freeze'].browse(active_ids).filtered(lambda record: record.state == 'frozen')
            values.update({
                'mode': 'release',
                'freeze_record_ids': [fields.Command.set(records.ids)],
            })
        elif active_model == 'sn.wsd.serial.identity' and active_ids:
            identity = self.env['sn.wsd.serial.identity'].browse(active_ids[:1])
            values.update({
                'mode': values.get('mode') or 'single',
                'serial_identity_id': identity.id,
                'serial_no': identity.name,
                'company_id': identity.company_id.id,
                'route_operation_id': identity._current_route_operation().id,
            })
        return values

    @api.onchange('serial_no')
    def _onchange_serial_no(self):
        if not self.serial_no:
            return
        identity = self.env['sn.wsd.serial.identity'].search([
            ('name', '=', self.serial_no.strip()),
        ], limit=1)
        self.serial_identity_id = identity
        if identity:
            self.company_id = identity.company_id
            self.route_operation_id = identity._current_route_operation()

    @api.onchange('serial_identity_id')
    def _onchange_serial_identity_id(self):
        if not self.serial_identity_id:
            return
        self.serial_no = self.serial_identity_id.name
        self.company_id = self.serial_identity_id.company_id
        self.route_operation_id = self.serial_identity_id._current_route_operation()

    @api.onchange('route_operation_id')
    def _onchange_route_operation_id(self):
        if self.route_operation_id:
            self.company_id = self.route_operation_id.company_id
            self.production_id = self.route_operation_id.mes_order_id.production_id

    def _resolve_single_serial(self):
        self.ensure_one()
        identity = self.serial_identity_id
        if not identity and self.serial_no:
            identity = self.env['sn.wsd.serial.identity'].search([
                ('name', '=', self.serial_no.strip()),
            ], limit=1)
        if not identity:
            raise UserError(_('Please select or enter a valid SN.'))
        return identity

    def _prepare_freeze_values(self, identity):
        self.ensure_one()
        if not self.freeze_reason:
            raise UserError(_('Freeze reason is required.'))
        return {
            'serial_identity_id': identity.id,
            'company_id': identity.company_id.id,
            'route_operation_id': (
                self.route_operation_id.id
                if self.route_operation_id
                else identity._current_route_operation().id
            ),
            'freeze_reason': self.freeze_reason,
        }

    def action_apply(self):
        self.ensure_one()
        freeze_model = self.env['sn.wsd.serial.freeze']
        if self.mode == 'release':
            records = self.freeze_record_ids.filtered(lambda record: record.state == 'frozen')
            if not records:
                raise UserError(_('Please select frozen records to release.'))
            records.action_release(release_reason=self.release_reason)
            return {'type': 'ir.actions.act_window_close'}

        if self.mode == 'single':
            identity = self._resolve_single_serial()
            freeze_model.create(self._prepare_freeze_values(identity))
            return {'type': 'ir.actions.act_window_close'}

        if not self.route_operation_id:
            raise UserError(_('Please select a route operation.'))
        # batch frame: SNs currently parked at the operation (WIP), skipping
        # scrapped, packed and already-frozen ones
        ScrapRecord = self.env['sn.wsd.scrap.record']
        PackRecord = self.env['sn.wsd.meter.pack.record']
        wips = self.env['sn.wsd.serial.wip'].search([
            ('route_operation_id', '=', self.route_operation_id.id),
        ])
        identities = self.env['sn.wsd.serial.identity']
        for wip in wips:
            identity = wip.serial_identity_id
            if identity.x_freeze_state == 'frozen':
                continue
            if ScrapRecord.search_count([
                    ('serial_identity_id', '=', identity.id),
                    ('state', '=', 'scrapped')]):
                continue
            if PackRecord.search_count([('serial_identity_id', '=', identity.id)]):
                continue
            identities |= identity
        if not identities:
            raise UserError(_('No freezable SNs were found on the selected route operation.'))
        freeze_model.create([self._prepare_freeze_values(identity) for identity in identities])
        return {'type': 'ir.actions.act_window_close'}
