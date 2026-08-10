from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SnWsdSerialFreezeWizard(models.TransientModel):
    _name = 'sn.wsd.serial.freeze.wizard'
    _description = 'SN Freeze Wizard'

    mode = fields.Selection(
        [
            ('single', 'Single SN Freeze'),
            ('workorder', 'Work Order Batch Freeze'),
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
    serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Meter Serial',
        check_company=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        check_company=True,
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
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
        elif active_model == 'sn.wsd.internal.serial' and active_ids:
            serial = self.env['sn.wsd.internal.serial'].browse(active_ids[:1])
            values.update({
                'mode': values.get('mode') or 'single',
                'serial_id': serial.id,
                'serial_no': serial.serial_no,
                'company_id': serial.company_id.id,
                'workorder_id': serial.current_workorder_id.id,
                'production_id': serial.production_id.id,
            })
        elif active_model == 'mrp.workorder' and active_ids:
            workorder = self.env['mrp.workorder'].browse(active_ids[:1])
            values.update({
                'mode': 'workorder',
                'company_id': workorder.company_id.id,
                'workorder_id': workorder.id,
                'production_id': workorder.production_id.id,
            })
        return values

    @api.onchange('serial_no')
    def _onchange_serial_no(self):
        if not self.serial_no:
            return
        serial = self.env['sn.wsd.internal.serial'].search([
            ('serial_no', '=', self.serial_no.strip()),
        ], limit=1)
        self.serial_id = serial
        if serial:
            self.company_id = serial.company_id
            self.production_id = serial.production_id
            self.workorder_id = serial.current_workorder_id

    @api.onchange('serial_id')
    def _onchange_serial_id(self):
        if not self.serial_id:
            return
        self.serial_no = self.serial_id.serial_no
        self.company_id = self.serial_id.company_id
        self.production_id = self.serial_id.production_id
        self.workorder_id = self.serial_id.current_workorder_id

    @api.onchange('workorder_id')
    def _onchange_workorder_id(self):
        if self.workorder_id:
            self.company_id = self.workorder_id.company_id
            self.production_id = self.workorder_id.production_id

    def _resolve_single_serial(self):
        self.ensure_one()
        serial = self.serial_id
        if not serial and self.serial_no:
            serial = self.env['sn.wsd.internal.serial'].search([
                ('serial_no', '=', self.serial_no.strip()),
            ], limit=1)
        if not serial:
            raise UserError(_('Please select or enter a valid SN.'))
        return serial

    def _prepare_freeze_values(self, serial):
        self.ensure_one()
        if not self.freeze_reason:
            raise UserError(_('Freeze reason is required.'))
        workorder = self.workorder_id or serial.current_workorder_id
        return {
            'serial_id': serial.id,
            'company_id': serial.company_id.id,
            'workorder_id': workorder.id,
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
            serial = self._resolve_single_serial()
            freeze_model.create(self._prepare_freeze_values(serial))
            return {'type': 'ir.actions.act_window_close'}

        if not self.workorder_id:
            raise UserError(_('Please select a work order.'))
        serials = self.workorder_id._get_freezable_internal_serials()
        if not serials:
            raise UserError(_('No freezable SNs were found on the selected work order.'))
        freeze_model.create([self._prepare_freeze_values(serial) for serial in serials])
        return {'type': 'ir.actions.act_window_close'}
