from odoo import _, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    picklight_enabled = fields.Boolean(
        string='Picklight Enabled', related='picking_type_id.picklight_enabled',
        readonly=True)
    picklight_command_ids = fields.One2many(
        'sn.wsd.picklight.command', 'picking_id', string='Picklight Commands')
    picklight_command_count = fields.Integer(
        string='Picklight Command Count', compute='_compute_picklight_command_count')

    def _compute_picklight_command_count(self):
        for picking in self:
            picking.picklight_command_count = len(picking.picklight_command_ids)

    def action_view_picklight_commands(self):
        self.ensure_one()
        return {
            'name': _('Picklight Commands'),
            'type': 'ir.actions.act_window',
            'res_model': 'sn.wsd.picklight.command',
            'view_mode': 'list,form',
            'domain': [('picking_id', '=', self.id)],
            'context': {'default_picking_id': self.id},
        }

    def action_picklight_start(self):
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            raise UserError(_('Picklight can only start for an open transfer.'))
        config = self.env['sn.wsd.picklight.config'].get_active(self.company_id)
        if not config:
            raise UserError(_('No active picklight service configuration exists for this company.'))
        locations = self.env['sn.wsd.picklight.location'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
            ('stock_location_id', 'in', (self.move_line_ids.location_id | self.move_ids.location_id).ids),
        ])
        if not locations:
            raise UserError(_('No picklight location is mapped to this transfer source location.'))
        details = []
        for location in locations:
            lines = self.move_line_ids.filtered(
                lambda line: line.location_id == location.stock_location_id)
            if lines:
                quantity = sum(lines.mapped('quantity_product_uom'))
                product = lines.product_id[:1]
                lot = lines.lot_id[:1]
            else:
                moves = self.move_ids.filtered(
                    lambda move: move.location_id == location.stock_location_id)
                quantity = sum(moves.mapped('product_uom_qty'))
                product = moves.product_id[:1]
                lot = self.env['stock.lot']
            details.append({
                'LocationId': location.code,
                'LightColor': location.light_color,
                'Twinkle': int(location.twinkle),
                'IsLocked': int(location.is_locked),
                'IsMustCollect': int(location.is_must_collect),
                'Quantity': int(quantity),
                'SubText': product.default_code or '',
                'BatchCode': lot.name or '',
                'Name': product.display_name or '',
                'R1': self.name,
                'R2': self.partner_id.display_name or '',
                'R3': product.display_name or '',
                'SubTitle': '',
                'Title': 'Pick',
                'Unit': product.uom_id.name[:1] if product.uom_id else '',
                'RelateToTower': True,
            })
        command = self.env['sn.wsd.picklight.command'].create({
            'company_id': self.company_id.id,
            'config_id': config.id,
            'picking_id': self.id,
            'command_type': 'post_info',
            'endpoint': config.endpoint_url('/api/Light/PostInfo/'),
            'request_payload': {'TwinkleTime': 0, 'Details': details},
        })
        command.send()
        return True

    def _picklight_command(self, command_type, path, payload):
        self.ensure_one()
        config = self.env['sn.wsd.picklight.config'].get_active(self.company_id)
        if not config:
            raise UserError(_('No active picklight service configuration exists for this company.'))
        command = self.env['sn.wsd.picklight.command'].create({
            'company_id': self.company_id.id,
            'config_id': config.id,
            'picking_id': self.id,
            'command_type': command_type,
            'endpoint': config.endpoint_url(path),
            'request_payload': payload,
        })
        command.send()
        return command

    def action_picklight_stop(self):
        self.ensure_one()
        config = self.env['sn.wsd.picklight.config'].get_active(self.company_id)
        if not config:
            raise UserError(_('No active picklight service configuration exists for this company.'))
        codes = self.picklight_command_ids.filtered(
            lambda command: command.state == 'sent').mapped('request_payload')
        location_codes = [
            detail.get('LocationId') for payload in codes
            for detail in (payload or {}).get('Details', [])
            if detail.get('LocationId')
        ]
        if not location_codes:
            return True
        command = self.env['sn.wsd.picklight.command'].create({
            'company_id': self.company_id.id,
            'config_id': config.id,
            'picking_id': self.id,
            'command_type': 'post_info',
            'endpoint': config.endpoint_url('/api/Light/PostInfo/'),
            'request_payload': {
                'TwinkleTime': 0,
                'Details': [{
                    'LocationId': code,
                    'LightColor': 0,
                    'Twinkle': 0,
                    'IsLocked': 0,
                    'IsMustCollect': 0,
                    'Quantity': 0,
                    'RelateToTower': True,
                } for code in location_codes],
            },
        })
        command.send()
        return True
