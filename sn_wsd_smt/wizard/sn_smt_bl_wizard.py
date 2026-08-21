import re

from odoo import _, fields, models
from odoo.exceptions import UserError


DEVICE_TABLE_PATTERN = re.compile(r'^\s*(\d+)\.([A-Za-z0-9_-]+)\s*$')


class SnSmtBlWizard(models.TransientModel):
    _name = 'sn.smt.bl.wizard'
    _description = 'SMT Offline Preparation Wizard'
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
    cart_input = fields.Char(string='Cart SN')
    feeder_input = fields.Char(string='Feeder SN')
    material_sn_input = fields.Char(string='Material SN', required=True)
    online_material_id = fields.Many2one('sn.smt.online.material', string='Target Position', readonly=True, check_company=True)
    cart_id = fields.Many2one('sn.smt.cart', string='Cart', readonly=True, check_company=True)
    feeder_id = fields.Many2one('sn.smt.feeder', string='Feeder', readonly=True, check_company=True)
    material_lot_id = fields.Many2one('stock.lot', string='Material Lot', readonly=True, check_company=True)
    message = fields.Char(string='Message', readonly=True)

    def _validate_production(self):
        self.ensure_one()
        if not self.production_id:
            raise UserError(_('Input value is empty.'))
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

    def _validate_loadpoint(self):
        self.ensure_one()
        production = self._validate_production()
        device_seq, table_no = self._parse_device_table()
        target = production.x_smt_online_material_ids.filtered(
            lambda line: line.device_seq == device_seq and line.table_no == table_no and line.loadpoint == self.loadpoint_input
        )[:1]
        if not target:
            same_table = production.x_smt_online_material_ids.filtered(
                lambda line: line.device_seq == device_seq and line.table_no == table_no
            )
            if not same_table:
                raise UserError(_('The current device table does not require offline preparation.'))
            raise UserError(_('The current loadpoint does not require offline preparation.'))
        if target.offline_material_ids:
            raise UserError(_('The current loadpoint is already prepared offline.'))
        self.online_material_id = target
        return target

    def _validate_feeder(self, online_material):
        self.ensure_one()
        if online_material.is_tray == 'Y':
            self.feeder_id = False
            return self.env['sn.smt.feeder']
        feeder = self.env['sn.smt.feeder'].search([
            ('feeder_sn', '=', self.feeder_input),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not feeder:
            raise UserError(_('The feeder SN does not exist.'))
        if feeder.status not in ('normal', 'in_use'):
            raise UserError(_('The feeder status is invalid.'))
        if not feeder.maintenance_ok:
            raise UserError(_('The feeder is not available for use because maintenance is not valid.'))
        if online_material.chanel_sn and feeder.channel_ids and online_material.chanel_sn not in feeder.channel_ids.mapped('channel_sn'):
            raise UserError(_('The feeder channel does not match the SMT position channel.'))
        self._check_feeder_mes_order_scope(feeder, self.production_id)
        self.feeder_id = feeder
        return feeder

    def _validate_cart(self):
        self.ensure_one()
        if not self.cart_input:
            self.cart_id = False
            return self.env['sn.smt.cart']
        cart = self.env['sn.smt.cart'].search([
            ('cart_sn', '=', self.cart_input),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not cart:
            cart = self.env['sn.smt.cart'].create({
                'cart_sn': self.cart_input,
                'company_id': self.production_id.company_id.id,
            })
        self.cart_id = cart
        return cart

    def _validate_material(self, online_material):
        self.ensure_one()
        if not self.material_sn_input:
            raise UserError(_('Input value is empty.'))
        material_lot = self.env['stock.lot'].search([
            ('name', '=', self.material_sn_input),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not material_lot:
            raise UserError(_('The material SN could not be resolved to a stock lot.'))
        if self.env['sn.smt.offline.material'].search_count([('material_lot_id', '=', material_lot.id)], limit=1):
            raise UserError(_('The material is already in use.'))
        if self.env['sn.smt.online.material'].search_count([('loaded_material_lot_id', '=', material_lot.id)], limit=1):
            raise UserError(_('The material is already loaded online.'))
        self._check_material_common_rules(self.production_id, online_material, material_lot)
        self.material_lot_id = material_lot
        return material_lot

    def action_validate(self):
        self.ensure_one()
        online_material = self._validate_loadpoint()
        self._validate_cart()
        self._validate_feeder(online_material)
        self._validate_material(online_material)
        self.message = _('Validation passed.')
        return True

    def action_save(self):
        self.ensure_one()
        online_material = self._validate_loadpoint()
        cart = self._validate_cart()
        feeder = self._validate_feeder(online_material)
        material_lot = self._validate_material(online_material)
        self.env['sn.smt.offline.material'].create({
            'online_material_id': online_material.id,
            'material_lot_id': material_lot.id,
            'cart_id': cart.id if cart else False,
            'feeder_id': feeder.id if feeder else False,
            'is_online': 'N',
            'is_repeat': 'N',
            'item_type': '0',
            'action_type': '5',
        })
        if feeder:
            feeder.write({'status': 'in_use', 'bound_production_id': self.production_id.id})
        if cart:
            cart.status = 'loaded'
        self._create_operation_bundle(
            self.production_id,
            online_material=online_material,
            operation_type='offline_prepare',
            material_lot=material_lot,
            feeder=feeder if feeder else False,
            cart=cart if cart else False,
            is_online='N',
            note='BL',
        )
        self.message = _('Offline preparation saved successfully.')
        return {'type': 'ir.actions.act_window_close'}
