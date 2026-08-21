import re

from odoo import fields, models, _
from odoo.exceptions import UserError


DEVICE_TABLE_PATTERN = re.compile(r'^\s*(\d+)\.([A-Za-z0-9_-]+)\s*$')


class SnSmtChangeWizard(models.TransientModel):
    _name = 'sn.smt.change.wizard'
    _description = 'SMT Change Material Wizard'
    _inherit = 'sn.smt.operation.mixin'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True, check_company=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', required=True, check_company=True)
    change_type = fields.Selection(
        [('change', 'Change'), ('continue', 'Continue')],
        string='Change Type',
        default='change',
        required=True,
    )
    device_table_input = fields.Char(string='Device.TABLE', required=True)
    loadpoint_input = fields.Char(string='Loadpoint', required=True)
    new_material_sn_input = fields.Char(string='New Material SN', required=True)
    material_sn_input = fields.Char(string='Old Material SN')
    feeder_input = fields.Char(string='New Feeder SN')
    message = fields.Char(string='Message', readonly=True)

    def _parse_device_table(self):
        self.ensure_one()
        match = DEVICE_TABLE_PATTERN.match(self.device_table_input or '')
        if not match:
            raise UserError(_('The device TABLE input is invalid.'))
        return int(match.group(1)), match.group(2)

    def _get_target_line(self):
        self.ensure_one()
        device_seq, table_no = self._parse_device_table()
        line = self.production_id.x_smt_online_material_ids.filtered(
            lambda rec: rec.device_seq == device_seq and rec.table_no == table_no and rec.loadpoint == self.loadpoint_input
        )[:1]
        if not line or line.is_load != 'Y':
            raise UserError(_('The selected loadpoint is not loaded.'))
        return line

    def _get_new_lot(self, target_line):
        self.ensure_one()
        if not self.new_material_sn_input:
            raise UserError(_('The new material SN is empty.'))
        lot = self.env['stock.lot'].search([
            ('name', '=', self.new_material_sn_input),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not lot:
            raise UserError(_('The material SN could not be resolved to a material item code.'))
        if target_line.loaded_material_lot_id and lot == target_line.loaded_material_lot_id:
            raise UserError(_('The new SN cannot be the same as the current SN.'))
        if self.env['sn.smt.online.material'].search_count([('loaded_material_lot_id', '=', lot.id)], limit=1):
            raise UserError(_('The material is already online.'))
        self._check_material_common_rules(
            self.production_id,
            target_line,
            lot,
            require_issue=True,
            require_positive_qty=True,
        )
        return lot

    def _get_new_feeder(self, target_line):
        self.ensure_one()
        if target_line.is_tray == 'Y':
            return self.env['sn.smt.feeder']
        feeder_required = self._is_config_enabled('SMT018', self.production_id.company_id)
        if not self.feeder_input and feeder_required:
            raise UserError(_('The current continuation parameters require changing the feeder first.'))
        if not self.feeder_input:
            return target_line.loaded_feeder_id or self.env['sn.smt.feeder']
        feeder = self.env['sn.smt.feeder'].search([
            ('feeder_sn', '=', self.feeder_input),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not feeder:
            raise UserError(_('The feeder SN does not exist.'))
        if feeder.status not in ('normal', 'in_use'):
            raise UserError(_('The feeder status is invalid.'))
        if not feeder.maintenance_ok:
            raise UserError(_('The feeder maintenance status is expired and cannot be used.'))
        if target_line.chanel_sn and feeder.channel_ids and target_line.chanel_sn not in feeder.channel_ids.mapped('channel_sn'):
            raise UserError(_('The feeder channel does not match the loadpoint channel.'))
        if target_line.feeder_spec and feeder.feeder_spec and feeder.feeder_spec != target_line.feeder_spec:
            raise UserError(_('The feeder specification does not match the loadpoint feeder requirement.'))
        self._check_feeder_mes_order_scope(feeder, self.production_id)
        return feeder

    def _apply_change(self, target_line, new_lot, new_feeder=False, note='CHANGE'):
        self.ensure_one()
        old_lot = target_line.loaded_material_lot_id
        old_feeder = target_line.loaded_feeder_id
        if old_feeder and new_feeder and old_feeder != new_feeder:
            self._sync_feeder_binding_after_unload(self.production_id, old_feeder, self._get_unload_release_enabled(self.production_id))
        target_line.write({
            'loaded_material_lot_id': new_lot.id,
            'loaded_feeder_id': new_feeder.id if new_feeder else False,
            'replace_count': target_line.replace_count + 1,
            'is_qc_test': self._get_qc_flag(self.production_id),
        })
        target_line._set_loaded_quantity(new_lot)
        if new_feeder:
            new_feeder.write({'status': 'in_use', 'bound_production_id': self.production_id.id})
        old_trace = self.env['sn.smt.traceability'].search([
            ('production_id', '=', self.production_id.id),
            ('online_material_id', '=', target_line.id),
            ('material_lot_id', '=', old_lot.id if old_lot else False),
        ], limit=1, order='id desc')
        if old_trace:
            old_trace.write({'old_material_lot_id': old_lot.id})
        self.env['sn.smt.offline.material'].create({
            'online_material_id': target_line.id,
            'material_lot_id': new_lot.id,
            'old_material_lot_id': old_lot.id if old_lot else False,
            'feeder_id': new_feeder.id if new_feeder else False,
            'is_online': 'Y',
            'is_repeat': 'N',
            'item_type': '0',
            'action_type': '5',
            'change_type': self.change_type,
        })
        self._create_operation_bundle(
            self.production_id,
            online_material=target_line,
            operation_type=self.change_type,
            material_lot=new_lot,
            old_material_lot=old_lot if old_lot else False,
            feeder=new_feeder if new_feeder else False,
            is_online='Y',
            note=note,
        )
        self._sync_production_after_smt_change(self.production_id)

    def action_change(self):
        self.ensure_one()
        target_line = self._get_target_line()
        new_lot = self._get_new_lot(target_line)
        new_feeder = self._get_new_feeder(target_line)
        self._apply_change(target_line, new_lot, new_feeder=new_feeder, note='CHANGE')
        self.message = _('Material change or continuation completed.')
        return {'type': 'ir.actions.act_window_close'}

    def _get_target_line_by_material_sn(self, material_sn):
        self.ensure_one()
        lot = self.env['stock.lot'].search([
            ('name', '=', material_sn),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not lot:
            raise UserError(_('The old material SN could not be resolved to a material item code.'))
        line = self.production_id.x_smt_online_material_ids.filtered(
            lambda record: record.loaded_material_lot_id == lot and record.is_load == 'Y'
        )[:1]
        if not line:
            raise UserError(_('The material is not currently loaded.'))
        return line

    def action_change_by_material_sn(self):
        self.ensure_one()
        if not self.material_sn_input:
            raise UserError(_('The old material SN is empty.'))
        if not self.new_material_sn_input:
            raise UserError(_('The new material SN is empty.'))
        target_line = self._get_target_line_by_material_sn(self.material_sn_input)
        new_lot = self._get_new_lot(target_line)
        self._apply_change(target_line, new_lot, new_feeder=False, note='MATERIAL_REFILL')
        self.message = _('Material refill completed.')
        return {'type': 'ir.actions.act_window_close'}
