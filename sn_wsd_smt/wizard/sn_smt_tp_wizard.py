import re

from odoo import _, fields, models
from odoo.exceptions import UserError


DEVICE_TABLE_PATTERN = re.compile(r'^\s*(\d+)\.([A-Za-z0-9_-]+)\s*$')


class SnSmtTpWizard(models.TransientModel):
    _name = 'sn.smt.tp.wizard'
    _description = 'SMT Online Loading Wizard'
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
    loadpoint_input = fields.Char(string='Loadpoint', required=True)
    feeder_input = fields.Char(string='Feeder SN')
    material_sn_input = fields.Char(string='Material SN', required=True)
    online_material_id = fields.Many2one('sn.smt.online.material', string='Target Position', readonly=True, check_company=True)
    feeder_id = fields.Many2one('sn.smt.feeder', string='Feeder', readonly=True, check_company=True)
    material_lot_id = fields.Many2one('stock.lot', string='Material Lot', readonly=True, check_company=True)
    message = fields.Char(string='Message', readonly=True)

    def _validate_production(self):
        self.ensure_one()
        if not self.production_id:
            raise UserError(_('Input value is empty.'))
        if self.production_id.x_online_state != 'online' or self.production_id.x_smt_online_state != 'online':
            raise UserError(_('The manufacturing order is not online for SMT loading.'))
        if not self.production_id.x_smt_product_side:
            raise UserError(_('The manufacturing order is missing the SMT product side.'))
        if not self.production_id.x_smt_online_material_ids:
            raise UserError(_('No SMT online material positions were generated for the manufacturing order.'))
        return self.production_id

    def _parse_device_table(self):
        self.ensure_one()
        match = DEVICE_TABLE_PATTERN.match(self.device_table_input or '')
        if not match:
            raise UserError(_('The Device.TABLE input format is invalid.'))
        return int(match.group(1)), match.group(2)

    def _validate_online_scope(self):
        self.ensure_one()
        production = self._validate_production()
        device_seq, table_no = self._parse_device_table()
        waiting_lines = production.x_smt_online_material_ids.filtered(
            lambda line: line.device_seq == device_seq and line.table_no == table_no and line.is_load == 'N'
        )
        if not waiting_lines:
            raise UserError(_('The current device table does not require online loading.'))
        target = waiting_lines.filtered(lambda line: line.loadpoint == self.loadpoint_input)[:1]
        if not target:
            raise UserError(_('The current loadpoint does not require online loading.'))
        if target.is_skip == 'Y':
            raise UserError(_('The current loadpoint is skipped and does not require online loading.'))
        if target.is_load == 'Y':
            raise UserError(_('The current loadpoint is already loaded online.'))
        self.online_material_id = target
        return target

    def _validate_feeder(self, online_material):
        self.ensure_one()
        if not self.workcenter_id.x_smt_is_feeder_control or online_material.is_tray == 'Y':
            self.feeder_id = False
            return self.env['sn.smt.feeder']
        feeder = self.env['sn.smt.feeder'].search([
            ('name', '=', self.feeder_input),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not feeder:
            raise UserError(_('The feeder SN does not exist.'))
        if feeder.status not in ('1', '2'):
            raise UserError(_('The feeder status is invalid.'))
        if not feeder.maintenance_ok:
            raise UserError(_('The feeder is not available for use because maintenance is not valid.'))
        if online_material.chanel_sn and feeder.channel_sn and feeder.channel_sn != online_material.chanel_sn:
            raise UserError(_('The feeder channel does not match the SMT position channel.'))
        if online_material.feeder_spec and feeder.feeder_spec and feeder.feeder_spec != online_material.feeder_spec:
            raise UserError(_('The feeder specification does not match the SMT position requirement.'))
        self._check_feeder_mes_order_scope(feeder, self.production_id)
        self.feeder_id = feeder
        return feeder

    def _validate_material(self, online_material):
        self.ensure_one()
        material_lot = self.env['stock.lot'].search([
            ('name', '=', self.material_sn_input),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not material_lot:
            raise UserError(_('The material SN could not be resolved to a stock lot.'))
        if self.env['sn.smt.online.material'].search_count([('loaded_material_lot_id', '=', material_lot.id)], limit=1):
            raise UserError(_('The material is already loaded online.'))
        self._check_material_common_rules(
            self.production_id,
            online_material,
            material_lot,
            require_issue=True,
            require_positive_qty=True,
        )
        prepared_records = self.env['sn.smt.offline.material'].search([
            ('online_material_id', '=', online_material.id),
        ])
        if prepared_records and material_lot not in prepared_records.mapped('material_lot_id'):
            raise UserError(_('The current loadpoint is prepared with another material SN.'))
        self.material_lot_id = material_lot
        return material_lot

    def _get_lot_available_qty(self, material_lot):
        self.ensure_one()
        return material_lot.product_qty

    def _sync_feeder_line(self, online_material, material_lot):
        self.ensure_one()
        feeder_line = self.production_id.feeder_line_ids.filtered(
            lambda line: line.online_material_id == online_material
            and line.route_operation_id.operation_id.x_station_type == 'smt'
            and line.state == 'pending'
        )[:1]
        if not feeder_line:
            return self.env['mrp.feeder.line']
        feeder_line.write({
            'actual_product_id': material_lot.product_id.id,
            'lot_id': material_lot.id,
            'lot_name': material_lot.name,
            'loaded_qty': self._get_lot_available_qty(material_lot),
            'state': 'verified',
            'verify_datetime': fields.Datetime.now(),
            'verify_user_id': self.env.user.id,
        })
        return feeder_line

    def action_validate(self):
        self.ensure_one()
        online_material = self._validate_online_scope()
        self._validate_feeder(online_material)
        self._validate_material(online_material)
        self.message = _('Validation passed.')
        return True

    def action_save(self):
        self.ensure_one()
        online_material = self._validate_online_scope()
        feeder = self._validate_feeder(online_material)
        material_lot = self._validate_material(online_material)
        online_material.write({
            'loaded_material_lot_id': material_lot.id,
            'loaded_feeder_id': feeder.id if feeder else False,
            'is_load': 'Y',
            'is_qc_test': self._get_qc_flag(self.production_id),
        })
        online_material._set_loaded_quantity(material_lot)
        lot_vals = {
            'x_smt_is_reel': True,
            'x_smt_reel_state': 'loaded',
        }
        if not material_lot.x_smt_initial_qty:
            lot_vals['x_smt_initial_qty'] = self._get_lot_available_qty(material_lot)
        material_lot.write(lot_vals)
        offline_record = self.env['sn.smt.offline.material'].search([
            ('online_material_id', '=', online_material.id),
            ('material_lot_id', '=', material_lot.id),
        ], limit=1)
        if offline_record:
            offline_record.is_online = 'Y'
        else:
            offline_record = self.env['sn.smt.offline.material'].create({
                'online_material_id': online_material.id,
                'material_lot_id': material_lot.id,
                'feeder_id': feeder.id if feeder else False,
                'is_online': 'Y',
                'is_repeat': 'N',
                'item_type': '0',
                'action_type': '5',
            })
        if feeder:
            feeder.write({'status': '2', 'bound_production_id': self.production_id.id})
        self._sync_feeder_line(online_material, material_lot)
        self._create_operation_bundle(
            self.production_id,
            online_material=online_material,
            operation_type='online_load',
            material_lot=material_lot,
            feeder=feeder if feeder else False,
            cart=offline_record.cart_id if offline_record and offline_record.cart_id else False,
            is_online='Y',
            note='TP',
        )
        self._sync_production_after_smt_change(self.production_id)
        self.message = _('Online loading saved successfully.')
        return {'type': 'ir.actions.act_window_close'}
