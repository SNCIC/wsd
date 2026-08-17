from odoo import api, models


class MesSnTravel(models.Model):
    _inherit = 'sn.wsd.mes.sn.travel'

    @api.model
    def _resolve_workorder_arg(self, workorder=False):
        if not workorder:
            return self.env['mrp.workorder']
        if hasattr(workorder, 'ids'):
            return workorder.exists()
        return self.env['mrp.workorder'].browse(int(workorder)).exists()

    @api.model
    def _resolve_route_operation(self, station, production=False, workorder=False):
        operation_model = self.env['mrp.routing.workcenter']
        production = production or self.env['mrp.production']
        workorder = self._resolve_workorder_arg(workorder)
        if workorder and workorder.operation_id and station and workorder.operation_id.workcenter_id == station:
            return workorder.operation_id
        route = production.x_route_id or (workorder.production_id.x_route_id if workorder else False)
        if not route or not station:
            return operation_model
        bom = production.bom_id or (workorder.production_id.bom_id if workorder else False)
        return operation_model.search([
            ('bom_id', '=', bom.id),
            ('workcenter_id', '=', station.id),
            ('x_route_operation_id', '!=', False),
        ], order='sequence asc, id asc', limit=1)

    @api.model
    def serial_route_guard(self, serial_number, station_code, override_allowed=False, workorder=False, internal_serial_id=None):
        station = self.env['mrp.workcenter'].search([('code', '=', station_code)], limit=1)
        if not station:
            return self._mes_error('station_not_found', station_code=station_code)

        workorder = self._resolve_workorder_arg(workorder)
        internal_serial = self.env['sn.wsd.internal.serial'].browse(internal_serial_id).exists() if internal_serial_id else self.env['sn.wsd.internal.serial'].find_for_workorder_context(serial_number, workorder) if workorder else self.env['sn.wsd.internal.serial'].find_for_manufacturing_context(serial_number)
        production = workorder.production_id or (internal_serial.production_id if internal_serial else self.env['mrp.production'])
        operation = self._resolve_route_operation(station, production=production, workorder=workorder)

        if not internal_serial:
            if operation:
                return self._mes_ok(
                    allowed=bool(operation.x_allow_entry),
                    reason='entry_operation' if operation.x_allow_entry else 'route_entry_not_allowed',
                    latest_event=False,
                    serial_number=serial_number,
                    station_code=station_code,
                    serial_exists=False,
                    operation_id=operation.id,
                )
            return self._mes_error('route_operation_not_found', station_code=station_code)

        latest_event = self.latest_event_by_serial(serial_number, internal_serial_id=internal_serial.id)
        latest = latest_event.get('latest_event')
        if not latest:
            if operation:
                return self._mes_ok(
                    allowed=bool(operation.x_allow_entry),
                    reason='entry_operation' if operation.x_allow_entry else 'route_entry_not_allowed',
                    latest_event=False,
                    serial_number=serial_number,
                    station_code=station_code,
                    serial_exists=True,
                    operation_id=operation.id,
                )
            return self._mes_error('route_operation_not_found', station_code=station_code)

        latest_station = self.env['mrp.workcenter'].search([('code', '=', latest.get('workcenter_code'))], limit=1)
        latest_operation = self._resolve_route_operation(latest_station, production=production, workorder=workorder) if latest_station else self.env['mrp.routing.workcenter']

        if operation and operation.x_station_type == 'repair':
            return self._mes_ok(
                allowed=latest.get('result') in ('fail', 'hold'),
                reason='repair_allowed' if latest.get('result') in ('fail', 'hold') else 'repair_requires_fail_or_hold',
                latest_event=latest,
                serial_number=serial_number,
                station_code=station_code,
                operation_id=operation.id if operation else False,
            )

        if latest_operation and latest_operation.x_station_type == 'repair':
            route_allows_repair = operation.x_allow_repair_return if operation else False
            return self._mes_ok(
                allowed=route_allows_repair,
                reason='repair_return' if route_allows_repair else 'repair_return_not_allowed',
                latest_event=latest,
                serial_number=serial_number,
                station_code=station_code,
                operation_id=operation.id if operation else False,
            )

        if operation:
            if latest.get('workcenter_code') == station.code:
                if latest.get('requires_repair'):
                    return self._mes_ok(
                        allowed=False,
                        reason='repair_required',
                        latest_event=latest,
                        serial_number=serial_number,
                        station_code=station_code,
                        operation_id=operation.id,
                    )
                if latest.get('result') in ('fail', 'hold'):
                    return self._mes_ok(
                        allowed=True,
                        reason='ng_retry_reentry',
                        latest_event=latest,
                        serial_number=serial_number,
                        station_code=station_code,
                        operation_id=operation.id,
                    )
                return self._mes_ok(
                    allowed=bool(operation.x_allow_reentry),
                    reason='same_station_reentry' if operation.x_allow_reentry else 'same_station_reentry_not_allowed',
                    latest_event=latest,
                    serial_number=serial_number,
                    station_code=station_code,
                    operation_id=operation.id,
                )
            if not operation.blocked_by_operation_ids:
                return self._mes_ok(
                    allowed=bool(operation.x_allow_entry),
                    reason='entry_operation' if operation.x_allow_entry else 'missing_previous_route_operation',
                    latest_event=latest,
                    serial_number=serial_number,
                    station_code=station_code,
                    operation_id=operation.id,
                )
            if latest_operation and latest_operation in operation.blocked_by_operation_ids and latest.get('result') == 'pass':
                return self._mes_ok(
                    allowed=True,
                    reason='previous_route_operation_passed',
                    latest_event=latest,
                    serial_number=serial_number,
                    station_code=station_code,
                    operation_id=operation.id,
                )
            if override_allowed and operation.x_allow_skip_with_override:
                return self._mes_ok(
                    allowed=True,
                    reason='override_skip_allowed',
                    latest_event=latest,
                    serial_number=serial_number,
                    station_code=station_code,
                    operation_id=operation.id,
                )
            return self._mes_ok(
                allowed=False,
                reason='route_operation_mismatch',
                expected_previous_operations=operation.blocked_by_operation_ids.mapped('x_step_code') or operation.blocked_by_operation_ids.mapped('name'),
                latest_event=latest,
                serial_number=serial_number,
                station_code=station_code,
                operation_id=operation.id,
            )

        return self._mes_error('route_operation_not_found', station_code=station_code)
