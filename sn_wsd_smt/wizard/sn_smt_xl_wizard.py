import re

from odoo import fields, models, _
from odoo.exceptions import UserError


DEVICE_TABLE_PATTERN = re.compile(r'^\s*(\d+)\.([A-Za-z0-9_-]+)\s*$')
UNLOAD_SCOPE_SELECTION = [
    ('material', 'Material Reel'),
    ('station', 'Station'),
    ('cart', 'Cart'),
    ('table', 'TABLE'),
    ('machine', 'Machine'),
    ('line', 'Line'),
    ('changeover', 'Changeover'),
]


class SnSmtXlWizard(models.TransientModel):
    _name = 'sn.smt.xl.wizard'
    _description = 'SMT Unload Wizard'
    _inherit = 'sn.smt.operation.mixin'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True, check_company=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', required=True, check_company=True)
    unload_scope = fields.Selection(
        UNLOAD_SCOPE_SELECTION,
        string='Unload Scope',
        default='station',
        required=True,
    )
    device_table_input = fields.Char(string='Device.TABLE')
    loadpoint_input = fields.Char(string='Loadpoint')
    cart_input = fields.Char(string='Cart SN')
    material_sn_input = fields.Char(string='Material SN')
    message = fields.Char(string='Message', readonly=True)

    def _parse_device_table(self):
        self.ensure_one()
        if not self.device_table_input:
            return False, False
        match = DEVICE_TABLE_PATTERN.match(self.device_table_input or '')
        if not match:
            raise UserError(_('The device TABLE input is invalid.'))
        return int(match.group(1)), match.group(2)

    def _get_loaded_lines(self):
        self.ensure_one()
        return self.production_id.x_smt_online_material_ids.filtered(lambda line: line.is_load == 'Y')

    def _get_lines_for_device_table(self, require_table=True):
        self.ensure_one()
        device_seq, table_no = self._parse_device_table()
        if require_table and (device_seq is False or not table_no):
            raise UserError(_('The device TABLE input is invalid.'))
        return self._get_loaded_lines().filtered(
            lambda line: line.device_seq == device_seq and line.table_no == table_no
        )

    def _get_target_lines(self):
        self.ensure_one()
        loaded_lines = self._get_loaded_lines()
        if self.unload_scope == 'line':
            if not loaded_lines:
                raise UserError(_('The current line has no online materials.'))
            return loaded_lines
        if self.unload_scope == 'machine':
            device_lines = self._get_lines_for_device_table()
            if not device_lines:
                raise UserError(_('The current device has no online materials.'))
            device_seq = device_lines[:1].device_seq
            machine_lines = loaded_lines.filtered(lambda line: line.device_seq == device_seq)
            if not machine_lines:
                raise UserError(_('The current device has no online materials.'))
            return machine_lines
        if self.unload_scope == 'table':
            table_lines = self._get_lines_for_device_table()
            if not table_lines:
                raise UserError(_('The current device table has no online materials.'))
            return table_lines
        if self.unload_scope == 'station':
            if not self.loadpoint_input:
                raise UserError(_('The input value is empty.'))
            station_lines = self._get_lines_for_device_table().filtered(
                lambda line: line.loadpoint == self.loadpoint_input
            )
            if not station_lines:
                raise UserError(_('The selected loadpoint is not loaded.'))
            return station_lines
        if self.unload_scope == 'cart':
            if not self.cart_input:
                raise UserError(_('The input value is empty.'))
            cart = self.env['sn.smt.cart'].search([
                ('name', '=', self.cart_input),
                ('company_id', '=', self.production_id.company_id.id),
            ], limit=1)
            if not cart:
                raise UserError(_('The cart is not loaded.'))
            cart_lines = cart.offline_material_ids.filtered(lambda line: line.is_online == 'Y').mapped('online_material_id')
            if not cart_lines:
                raise UserError(_('The cart is not loaded.'))
            return cart_lines.filtered(lambda line: line.is_load == 'Y')
        if self.unload_scope == 'material':
            if not self.material_sn_input:
                raise UserError(_('The input value is empty.'))
            return self._get_target_lines_by_material_sn(self.material_sn_input)
        if self.unload_scope == 'changeover':
            if not self.device_table_input:
                raise UserError(_('The device TABLE input is invalid.'))
            changeover_lines = self._get_lines_for_device_table()
            if not changeover_lines:
                raise UserError(_('The current device table has no online materials.'))
            return changeover_lines
        raise UserError(_('Unknown unload scope.'))

    def action_unload(self):
        self.ensure_one()
        lines = self._get_target_lines()
        clear_online_table = self.unload_scope == 'line'
        self._finalize_unload_lines(
            self.production_id,
            lines,
            unload_scope=self.unload_scope,
            clear_online_table=clear_online_table,
        )
        if self.unload_scope == 'line':
            self.production_id.x_smt_material_table_id = False
            self.production_id.x_smt_online_state = 'draft'
            if hasattr(self.production_id, 'x_online_state') and self.production_id.x_online_state == 'online':
                self.production_id.action_set_offline()
                # keep the MES orders (制令单) in sync: a dedicated offline
                # action is still pending in the execution layer
                self.production_id.x_mes_order_ids.filtered('x_online_date').write({'x_online_date': False})
        elif self.unload_scope == 'changeover':
            self.production_id.x_smt_online_state = 'changeover'
        self.message = _('Unload completed.')
        return {'type': 'ir.actions.act_window_close'}

    def _get_target_lines_by_material_sn(self, material_sn):
        self.ensure_one()
        lot = self.env['stock.lot'].search([
            ('name', '=', material_sn),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not lot:
            raise UserError(_('The material SN could not be resolved to a material item code.'))
        lines = self.production_id.x_smt_online_material_ids.filtered(
            lambda line: line.loaded_material_lot_id == lot and line.is_load == 'Y'
        )
        if not lines:
            raise UserError(_('The material is not currently loaded.'))
        return lines

    def action_unload_by_material_sn(self):
        self.ensure_one()
        if not self.material_sn_input:
            raise UserError(_('The input value is empty.'))
        lines = self._get_target_lines_by_material_sn(self.material_sn_input)
        self._finalize_unload_lines(
            self.production_id,
            lines,
            unload_scope='material',
            clear_online_table=False,
        )
        self.message = _('Unload completed.')
        return {'type': 'ir.actions.act_window_close'}
