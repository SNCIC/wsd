from odoo import api, models


class MesSnTravel(models.Model):
    _inherit = 'sn.wsd.mes.sn.travel'

    @api.model
    def _skip_resolve_production(self, serial_number=False, route_operation=False, internal_serial_id=None):
        if route_operation and not hasattr(route_operation, 'exists'):
            route_operation = self.env['sn.wsd.mes.order.route.operation'].browse(route_operation)
        route_operation = route_operation.exists() if route_operation else self.env['sn.wsd.mes.order.route.operation']
        if route_operation:
            return route_operation.mes_order_id.production_id
        internal_serial = self.env['sn.wsd.internal.serial'].browse(internal_serial_id).exists() if internal_serial_id else self.env['sn.wsd.internal.serial'].search([('serial_no', '=', serial_number)], limit=1) if serial_number else self.env['sn.wsd.internal.serial']
        return internal_serial.production_id if internal_serial else self.env['mrp.production']

    @api.model
    def _skip_get_effective_blockers(self, operation, mes_order):
        if not operation or not mes_order:
            return self.env['sn.wsd.mes.order.route.operation']
        blockers = operation.blocked_by_ids
        if not blockers:
            return blockers
        skipped_route_operations = self.env['sn.wsd.skip.request.line'].get_approved_skip_route_operations(
            mes_order,
            mes_order.x_route_operation_ids.filtered(lambda route_operation: route_operation in blockers),
        )
        return blockers - skipped_route_operations

    @api.model
    def serial_route_guard(self, serial_number, station_code, override_allowed=False, route_operation_id=None, internal_serial_id=None):
        result = super().serial_route_guard(
            serial_number,
            station_code,
            override_allowed=override_allowed,
            route_operation_id=route_operation_id,
            internal_serial_id=internal_serial_id,
        )
        if result.get('error') or result.get('allowed') is not False:
            return result

        operation = self.env['sn.wsd.mes.order.route.operation'].browse(result.get('operation_id')).exists()
        production = self._skip_resolve_production(
            serial_number=serial_number,
            route_operation=route_operation_id,
            internal_serial_id=internal_serial_id,
        )
        if not operation or not production:
            return result

        mes_order = operation.mes_order_id
        effective_blockers = self._skip_get_effective_blockers(operation, mes_order)
        original_blockers = operation.blocked_by_ids
        if not original_blockers or len(effective_blockers) == len(original_blockers):
            return result

        latest = result.get('latest_event') or {}
        latest_station = self.env['mrp.workcenter'].search([('code', '=', latest.get('workcenter_code'))], limit=1) if latest else self.env['mrp.workcenter']
        latest_operation = self._resolve_route_operation(
            latest_station,
            production=production,
            route_operation=False,
        ) if latest_station else self.env['sn.wsd.mes.order.route.operation']
        latest_passed = latest_operation and latest_operation in effective_blockers and latest.get('result') == 'pass'

        if not effective_blockers or latest_passed:
            result.update({
                'allowed': True,
                'reason': 'approved_skip_request',
                'effective_previous_operations': effective_blockers.mapped('x_step_code') or effective_blockers.mapped('display_label'),
                'skipped_previous_operations': (original_blockers - effective_blockers).mapped('x_step_code') or (original_blockers - effective_blockers).mapped('display_label'),
            })
        return result
