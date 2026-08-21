import re

from odoo import fields, models, _
from odoo.exceptions import UserError


DEVICE_TABLE_PATTERN = re.compile(r'^\s*(\d+)\.([A-Za-z0-9_-]+)\s*$')


class SnSmtLcslWizard(models.TransientModel):
    _name = 'sn.smt.lcsl.wizard'
    _description = 'SMT Cart Loading Wizard'
    _inherit = 'sn.smt.operation.mixin'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True, check_company=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', required=True, check_company=True)
    device_table_input = fields.Char(string='Device.TABLE', required=True)
    cart_input = fields.Char(string='Cart SN', required=True)
    cart_id = fields.Many2one('sn.smt.cart', string='Cart', readonly=True, check_company=True)
    message = fields.Char(string='Message', readonly=True)

    def _validate_scope(self):
        self.ensure_one()
        match = DEVICE_TABLE_PATTERN.match(self.device_table_input or '')
        if not match:
            raise UserError(_('The device TABLE input is invalid.'))
        device_seq = int(match.group(1))
        table_no = match.group(2)
        waiting_lines = self.production_id.x_smt_online_material_ids.filtered(
            lambda line: line.device_seq == device_seq and line.table_no == table_no and line.is_load == 'N'
        )
        if not waiting_lines:
            raise UserError(_('The current device TABLE does not need loading.'))
        cart = self.env['sn.smt.cart'].search([
            ('cart_sn', '=', self.cart_input),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not cart or not cart.offline_material_ids:
            raise UserError(_('The cart has no prepared materials.'))
        self.cart_id = cart
        cart_lines = cart.offline_material_ids.filtered(
            lambda line: line.device_seq == device_seq and line.table_no == table_no and line.production_id == self.production_id
        )
        if not cart_lines:
            other_production_lines = cart.offline_material_ids.filtered(lambda line: line.production_id == self.production_id)
            if other_production_lines:
                raise UserError(_('The cart prepared materials do not match the current device TABLE requirements.'))
            raise UserError(_('The cart prepared materials do not match the current manufacturing order requirements.'))
        unmatched = cart_lines.filtered(lambda line: line.online_material_id not in waiting_lines)
        if unmatched:
            raise UserError(_('The current machine loading requirements do not include the offline prepared materials.'))
        return cart_lines

    def action_load(self):
        self.ensure_one()
        cart_lines = self._validate_scope()
        qc_flag = self._get_qc_flag(self.production_id)
        for line in cart_lines:
            line.online_material_id.write({
                'loaded_material_lot_id': line.material_lot_id.id,
                'loaded_feeder_id': line.feeder_id.id,
                'is_load': 'Y',
                'is_qc_test': qc_flag,
            })
            line.is_online = 'Y'
            if line.feeder_id:
                line.feeder_id.write({
                    'status': 'in_use',
                    'bound_production_id': self.production_id.id,
                })
            self._create_operation_bundle(
                self.production_id,
                online_material=line.online_material_id,
                operation_type='cart_load',
                material_lot=line.material_lot_id,
                feeder=line.feeder_id if line.feeder_id else False,
                cart=self.cart_id,
                is_online='Y',
                note='LCSL',
            )
        self.cart_id.status = 'loaded'
        self._sync_production_after_smt_change(self.production_id)
        self.message = _('Cart loading saved successfully.')
        return {'type': 'ir.actions.act_window_close'}
