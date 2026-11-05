from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_is_picklight_putaway = fields.Boolean(
        string='Picklight Putaway',
        compute='_compute_x_is_picklight_putaway',
        help='Technical flag used by the views: the operation brings goods to '
             'their final stock location, i.e. where rack allocation applies.',
    )

    @api.depends('picking_id.picking_type_id', 'picking_id.state')
    def _compute_x_is_picklight_putaway(self):
        for move in self:
            move.x_is_picklight_putaway = move._is_picklight_putaway_picking()

    def _is_picklight_putaway_picking(self):
        """Whether the move belongs to the operation that stores goods in stock.

        With a three-step reception the rack allocation happens on the storage
        transfer (quality -> stock); one/two-step receptions store the goods
        directly on the receipt.
        """
        self.ensure_one()
        picking = self.picking_id
        if not picking or picking.state in ('done', 'cancel'):
            return False
        picking_type = picking.picking_type_id
        warehouse = picking_type.warehouse_id
        store_type = warehouse.store_type_id if warehouse else False
        if store_type and store_type.active:
            return picking_type == store_type
        return picking_type.code == 'incoming'

    def action_auto_fill_large_rack_locations(self):
        return self._action_auto_fill_picklight_locations('large')

    def action_auto_fill_small_rack_locations(self):
        return self._action_auto_fill_picklight_locations('small')

    def action_reset_rack_locations(self):
        return self.move_line_ids._action_reset_picklight_locations()

    def action_light_receipt_destination_locations(self):
        return self._action_light_receipt_destination_locations(True)

    def action_turn_off_receipt_destination_locations(self):
        return self._action_light_receipt_destination_locations(False)

    def _action_auto_fill_picklight_locations(self, shelf_type):
        self.ensure_one()
        if not self._is_picklight_putaway_picking():
            raise UserError(_('Automatic rack allocation is only available for storage operations.'))
        return self.move_line_ids._action_auto_fill_picklight_locations(shelf_type)

    def _action_light_receipt_destination_locations(self, light_on):
        self.ensure_one()
        if not self._is_picklight_putaway_picking():
            raise UserError(_('Picklight is only available for open storage operations.'))

        lines = self.move_line_ids.filtered('location_dest_id')
        locations = self.env['sn.wsd.picklight.location'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
            ('shelf_id.active', '=', True),
            ('stock_location_id', 'in', lines.location_dest_id.ids),
        ])
        if not locations:
            raise UserError(_(
                'No picklight location is mapped to this receipt destination location.'
            ))

        for config in locations.shelf_id.config_id:
            details = []
            for location in locations.filtered(
                lambda record: record.shelf_id.config_id == config
            ):
                location_lines = lines.filtered(
                    lambda line: line.location_dest_id == location.stock_location_id
                )
                product = location_lines.product_id[:1]
                lot = location_lines.lot_id[:1]
                details.append({
                    'LocationId': location.code,
                    'LightColor': 128 if light_on else 0,
                    'Twinkle': int(location.twinkle) if light_on else 0,
                    'IsLocked': int(location.is_locked) if light_on else 0,
                    'IsMustCollect': int(location.is_must_collect) if light_on else 0,
                    'Quantity': int(sum(location_lines.mapped('quantity_product_uom')))
                    if light_on else 0,
                    'SubText': product.default_code or '',
                    'BatchCode': lot.name or '',
                    'Name': product.display_name or '',
                    'R1': self.picking_id.name or '',
                    'R2': self.picking_id.partner_id.display_name or '',
                    'R3': product.display_name or '',
                    'SubTitle': '',
                    'Title': 'Receipt',
                    'Unit': product.uom_id.name or '',
                    'RelateToTower': True,
                })
            command = self.env['sn.wsd.picklight.command'].create({
                'company_id': self.company_id.id,
                'config_id': config.id,
                'picking_id': self.picking_id.id,
                'command_type': 'post_info',
                'endpoint': config.endpoint_url('/api/Light/PostInfo/'),
                'request_payload': {'TwinkleTime': 0, 'Details': details},
            })
            command.send()
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_stock.refresh_current_view',
        }
