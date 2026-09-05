from odoo import _, models
from odoo.exceptions import UserError


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def action_auto_fill_large_rack_locations(self):
        return self._action_auto_fill_picklight_locations('large')

    def action_auto_fill_small_rack_locations(self):
        return self._action_auto_fill_picklight_locations('small')

    def _action_auto_fill_picklight_locations(self, shelf_type):
        if not self:
            raise UserError(_('Select at least one receipt operation line.'))
        if any(line.picking_code != 'incoming' for line in self):
            raise UserError(_('Automatic rack allocation is only available for receipt operations.'))
        if any(line.state in ('done', 'cancel') for line in self):
            raise UserError(_('Completed or cancelled operation lines cannot be allocated.'))

        pickings = self.picking_id
        if len(pickings) != 1:
            raise UserError(_('Select operation lines from one receipt only.'))
        picking = pickings
        existing_picklight_locations = self.env['sn.wsd.picklight.location'].search([
            ('company_id', '=', picking.company_id.id),
            ('active', '=', True),
        ])
        existing_picklight_stock_location_ids = set(
            existing_picklight_locations.stock_location_id.ids
        )
        lines_to_allocate = self.filtered(
            lambda line: line.location_dest_id.id not in existing_picklight_stock_location_ids
        ).sorted(lambda line: (line.lot_id.name or '', line.id))
        if not lines_to_allocate:
            raise UserError(_('The selected operation lines already have picklight locations.'))

        candidates = self.env['sn.wsd.picklight.location'].search([
            ('company_id', '=', picking.company_id.id),
            ('active', '=', True),
            ('shelf_id.active', '=', True),
            ('shelf_id.shelf_type', '=', shelf_type),
            ('stock_location_id.active', '=', True),
            ('stock_location_id.usage', '=', 'internal'),
            ('stock_location_id', 'child_of', picking.location_dest_id.id),
        ], order=(
            'shelf_allocation_sequence, shelf_id, position_group, '
            'position_layer_number, position_number, code, id'
        )).filtered(lambda location: location.position_number > 0)
        if not candidates:
            raise UserError(_('No active picklight locations are configured for this rack type.'))

        # Lock candidates before checking occupancy so concurrent allocations cannot reuse a location.
        self.env.cr.execute(
            'SELECT id FROM sn_wsd_picklight_location WHERE id = ANY(%s) FOR UPDATE',
            [candidates.ids],
        )
        occupied_stock_location_ids = set(self.env['stock.quant'].search([
            ('location_id', 'in', candidates.stock_location_id.ids),
            ('quantity', '>', 0),
        ]).mapped('location_id').ids)
        pending_stock_location_ids = set(self.env['stock.move.line'].search([
            ('location_dest_id', 'in', candidates.stock_location_id.ids),
            ('state', 'not in', ('done', 'cancel')),
            ('id', 'not in', lines_to_allocate.ids),
        ]).mapped('location_dest_id').ids)
        free_locations = candidates.filtered(
            lambda location: location.stock_location_id.id not in occupied_stock_location_ids
            and location.stock_location_id.id not in pending_stock_location_ids)
        required_count = len(lines_to_allocate)
        if len(free_locations) < required_count:
            raise UserError(_(
                'Not enough free picklight locations. %(required)s are required, but only %(available)s are available.',
                required=required_count,
                available=len(free_locations),
            ))

        allocated_locations = self._get_continuous_locations(free_locations, required_count)
        if not allocated_locations:
            allocated_locations = free_locations[:required_count]
        for line, location in zip(lines_to_allocate, allocated_locations):
            line.location_dest_id = location.stock_location_id
        return True

    def _get_continuous_locations(self, free_locations, required_count):
        current_run = self.env['sn.wsd.picklight.location']
        previous_location = self.env['sn.wsd.picklight.location']
        for location in free_locations:
            if (
                previous_location
                and location.shelf_id == previous_location.shelf_id
                and self._locations_are_consecutive(previous_location, location)
            ):
                current_run |= location
            else:
                current_run = location
            if len(current_run) >= required_count:
                return current_run[:required_count]
            previous_location = location
        return self.env['sn.wsd.picklight.location']

    @staticmethod
    def _locations_are_consecutive(previous_location, location):
        """Return whether two configured positions are physically adjacent."""
        if previous_location.shelf_id != location.shelf_id:
            return False
        if previous_location.position_group == location.position_group:
            if previous_location.position_layer_number == location.position_layer_number:
                return location.position_number == previous_location.position_number + 1
            return (
                previous_location.position_number == 100
                and location.position_number == 1
                and location.position_layer_number == previous_location.position_layer_number + 1
            )
        return (
            previous_location.position_number == 100
            and location.position_number == 1
            and location.position_layer_number == 1
            and location.position_group == StockMoveLine._next_position_group(
                previous_location.position_group
            )
        )

    @staticmethod
    def _next_position_group(position_group):
        """Increment an alphabetic layer group, for example A to B or Z to AA."""
        letters = list(position_group)
        for index in range(len(letters) - 1, -1, -1):
            if letters[index] != 'Z':
                letters[index] = chr(ord(letters[index]) + 1)
                return ''.join(letters)
            letters[index] = 'A'
        return 'A' + ''.join(letters)
