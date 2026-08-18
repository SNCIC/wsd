from odoo import models
from odoo.exceptions import ValidationError


class MrpWorkorderMes(models.Model):
    _inherit = 'mrp.workorder'

    def _mes_get_or_create_finished_serial(self, serial_number):
        self.ensure_one()
        return self.env['sn.wsd.internal.serial'].find_for_workorder_context(serial_number, self)

    def _mes_prepare_execution_context(self, serial_number=None, operator_code=None, note=None):
        self.ensure_one()
        station = self.x_mes_workcenter_id
        serial = self.env['sn.wsd.internal.serial']
        if serial_number:
            serial = self._mes_get_or_create_finished_serial(serial_number)
            if serial:
                serial.write({
                    'current_production_id': self.production_id.id,
                    'current_workorder_id': self.id,
                    'current_operation_id': self.operation_id.id,
                    'current_workcenter_id': self.workcenter_id.id,
                })
        return {'workorder': self, 'station': station, 'serial': serial, 'operator_code': operator_code, 'note': note}

    def _mes_set_serial_qty_producing(self, serial):
        self.ensure_one()
        return

    def _mes_find_existing_travel_event(self, external_event_id=None, source_system=None):
        self.ensure_one()
        if not external_event_id:
            return self.env['sn.wsd.mes.sn.travel']
        domain = [
            ('workorder_id', '=', self.id),
            ('external_event_id', '=', external_event_id),
        ]
        if source_system:
            domain.append(('source_system', '=', source_system))
        return self.env['sn.wsd.mes.sn.travel'].search(domain, limit=1)

    def _mes_find_successful_station_event(self, serial):
        self.ensure_one()
        if not serial:
            return self.env['sn.wsd.mes.sn.travel']
        station_code = self.x_mes_workcenter_id.code if self.x_mes_workcenter_id else False
        domain = [
            ('internal_serial_id', '=', serial.id),
            ('workorder_id', '=', self.id),
            ('event_type', 'in', ('complete', 'pass')),
            ('result', '=', 'pass'),
        ]
        if station_code:
            domain.append(('workcenter_code', '=', station_code))
        return self.env['sn.wsd.mes.sn.travel'].search(
            domain,
            order='event_time desc, id desc',
            limit=1,
        )

    def _mes_validate_execution(self, serial_number=None, allow_restart=False, override_route=False):
        self.ensure_one()
        api = self.env['sncic.mes.api.mixin']
        if not self.x_mes_workcenter_id:
            return api._mes_error('station_not_mapped', workorder_id=self.id)
        if self.state in ('done', 'cancel'):
            return api._mes_error('invalid_workorder_state', state=self.state, workorder_id=self.id)
        if serial_number:
            serial = self._mes_get_or_create_finished_serial(serial_number)
            if not serial:
                return api._mes_error('serial_not_found', serial_number=serial_number)
            if not serial.active:
                return api._mes_error('serial_inactive', serial_number=serial_number, internal_serial_id=serial.id)
            if serial.product_id != self.product_id:
                return api._mes_error(
                    'serial_product_mismatch',
                    serial_number=serial_number,
                    expected_product_id=self.product_id.id,
                    actual_product_id=serial.product_id.id,
                )
            if (
                serial.production_id
                and serial.production_id != self.production_id
            ):
                return api._mes_error(
                    'serial_production_mismatch',
                    serial_number=serial_number,
                    expected_production_id=self.production_id.id,
                    actual_production_id=serial.production_id.id,
                )
            if (
                serial.current_production_id
                and serial.current_production_id != self.production_id
            ):
                return api._mes_error(
                    'serial_current_production_mismatch',
                    serial_number=serial_number,
                    expected_production_id=self.production_id.id,
                    actual_production_id=serial.current_production_id.id,
                )
            if serial.final_result == 'scrap':
                return api._mes_error('serial_scrapped', serial_number=serial_number, internal_serial_id=serial.id)
            if serial.pack_date:
                return api._mes_error('serial_already_packed', serial_number=serial_number, internal_serial_id=serial.id)
            successful_event = self._mes_find_successful_station_event(serial)
            if successful_event:
                return api._mes_error(
                    'serial_already_processed_on_station',
                    serial_number=serial_number,
                    latest_event={
                        'id': successful_event.id,
                        'workcenter_code': successful_event.workcenter_code,
                        'event_type': successful_event.event_type,
                        'result': successful_event.result,
                        'event_time': successful_event.event_time,
                        'retry_sequence': successful_event.retry_sequence,
                        'retry_limit': successful_event.retry_limit,
                        'requires_repair': successful_event.requires_repair,
                        'is_rework_pass': successful_event.is_rework_pass,
                        'rework_source_workorder_id': successful_event.rework_source_workorder_id.id,
                    },
                    station_code=self.x_mes_workcenter_id.code,
                )
            route_guard = self.env['sn.wsd.mes.sn.travel'].serial_route_guard(
                serial_number,
                self.x_mes_workcenter_id.code,
                override_allowed=override_route,
                workorder=self,
                internal_serial_id=serial.id,
            )
            if route_guard.get('error'):
                return route_guard
            if route_guard.get('allowed') is False:
                return api._mes_error(
                    'station_route_blocked',
                    reason=route_guard.get('reason'),
                    latest_event=route_guard.get('latest_event'),
                    expected_previous_station=route_guard.get('expected_previous_station'),
                    expected_previous_operations=route_guard.get('expected_previous_operations'),
                    operation_id=route_guard.get('operation_id'),
                    serial_number=serial_number,
                    station_code=self.x_mes_workcenter_id.code,
                )
            latest_event = self.env['sn.wsd.mes.sn.travel'].latest_event_by_serial(
                serial_number, internal_serial_id=serial.id,
            )
            if latest_event.get('error'):
                return latest_event
            latest = latest_event.get('latest_event')
            if latest and latest.get('station_code') == self.x_mes_workcenter_id.code and latest.get('event_type') in ('complete', 'pass'):
                return api._mes_error('serial_already_processed_on_station', serial_number=serial_number, latest_event=latest, station_code=self.x_mes_workcenter_id.code)
        return api._mes_ok()

    def action_mes_start(
        self,
        serial_number=None,
        operator_code=None,
        note=None,
        override_route=False,
        external_event_id=None,
        request_id=None,
        source_system=None,
    ):
        self.ensure_one()
        api = self.env['sncic.mes.api.mixin']
        if self.state not in ('ready', 'progress'):
            return api._mes_error('workorder_not_ready', state=self.state, workorder_id=self.id)
        validation = self._mes_validate_execution(
            serial_number=serial_number,
            allow_restart=self.state == 'progress',
            override_route=override_route,
        )
        if validation.get('error'):
            return validation
        payload = self._mes_prepare_execution_context(serial_number=serial_number, operator_code=operator_code, note=note)
        if payload['serial']:
            self._mes_set_serial_qty_producing(payload['serial'])
        self.button_start()
        if payload['serial']:
            self.env['sn.wsd.mes.sn.travel'].record_event(
                serial_number=payload['serial'].serial_no,
                event_type='start',
                workcenter_code=payload['station'].code if payload['station'] else None,
                workorder_id=self.id,
                production_id=self.production_id.id,
                operator_code=operator_code,
                note=note,
                external_event_id=external_event_id,
                request_id=request_id,
                source_system=source_system,
            )
        if note:
            self.x_mes_execution_note = note
        return api._mes_ok(workorder_id=self.id, state=self.state, serial_number=payload['serial'].serial_no if payload['serial'] else False)

    def action_mes_complete(
        self,
        serial_number=None,
        operator_code=None,
        note=None,
        override_route=False,
        external_event_id=None,
        request_id=None,
        source_system=None,
    ):
        self.ensure_one()
        api = self.env['sncic.mes.api.mixin']
        existing_event = self._mes_find_existing_travel_event(
            external_event_id=external_event_id,
            source_system=source_system,
        )
        if existing_event:
            return api._mes_ok(
                duplicated=True,
                travel_id=existing_event.id,
                workorder_id=self.id,
                state=self.state,
                qty_produced=self.qty_produced,
                qty_output_total=self.qty_produced,
                qty_output_total_label='cumulative_output_qty',
                qty_pass=self.x_meter_qty_pass,
                serial_number=existing_event.internal_serial_id.serial_no,
            )
        validation = self._mes_validate_execution(
            serial_number=serial_number,
            allow_restart=True,
            override_route=override_route,
        )
        if validation.get('error'):
            return validation
        payload = self._mes_prepare_execution_context(serial_number=serial_number, operator_code=operator_code, note=note)
        if payload['serial']:
            self._mes_set_serial_qty_producing(payload['serial'])
        if self.state == 'ready':
            self.button_start()
        is_rework_pass = bool(payload['serial'] and payload['serial']._workorder_in_current_rework_window(self))
        rework_source_workorder = payload['serial'].x_rework_source_workorder_id if is_rework_pass else self.env['mrp.workorder']
        smt_consumption = self.env['sn.smt.material.consumption']
        consumed_records = smt_consumption
        if payload['serial']:
            try:
                consumed_records = smt_consumption.consume_for_serial(
                    self,
                    payload['serial'],
                    operator_code=operator_code,
                    external_event_id=external_event_id,
                    source_system=source_system,
                    note=note,
                )
            except ValidationError as error:
                return api._mes_error(
                    'smt_material_consumption_failed',
                    message=str(error),
                    serial_number=payload['serial'].serial_no,
                    workorder_id=self.id,
                )
        if payload['serial']:
            self.env['sn.wsd.mes.sn.travel'].record_event(
                serial_number=payload['serial'].serial_no,
                event_type='complete',
                workcenter_code=payload['station'].code if payload['station'] else None,
                workorder_id=self.id,
                production_id=self.production_id.id,
                operator_code=operator_code,
                result='pass',
                note=note,
                external_event_id=external_event_id,
                request_id=request_id,
                source_system=source_system,
                is_rework_pass=is_rework_pass,
                rework_source_workorder_id=rework_source_workorder.id if rework_source_workorder else False,
            )
            if is_rework_pass:
                payload['serial']._mark_rework_step_passed(self)
        if note:
            self.x_mes_execution_note = note
        return api._mes_ok(
            workorder_id=self.id,
            state=self.state,
            qty_produced=self.qty_produced,
            qty_output_total=self.qty_produced,
            qty_output_total_label='cumulative_output_qty',
            qty_pass=self.x_meter_qty_pass,
            smt_consumption_ids=consumed_records.ids,
            smt_consumption_count=len(consumed_records),
            serial_number=payload['serial'].serial_no if payload['serial'] else False,
        )

    def action_mes_finish_if_complete(self):
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            return True
        if self.product_uom_id.compare(self.qty_produced, self.qty_production) < 0:
            return False
        self.button_finish()
        return True

    def action_mes_log_test(
        self,
        serial_number,
        result='pass',
        operator_code=None,
        cycle_time_sec=None,
        basic_error=None,
        phase_error=None,
        aging_temp_c=None,
        tester_channel=None,
        note=None,
        payload=None,
        external_event_id=None,
        request_id=None,
        source_system=None,
        retry_sequence=0,
        retry_limit=0,
        requires_repair=False,
        is_rework_pass=False,
        rework_source_workorder_id=None,
    ):
        self.ensure_one()
        validation = self._mes_validate_execution(serial_number=serial_number, allow_restart=True)
        if validation.get('error'):
            return validation
        station_code = self.x_mes_workcenter_id.code if self.x_mes_workcenter_id else None
        route_operation = self.operation_id.x_route_operation_id if self.operation_id else self.env['sn.wsd.process.route.operation']
        station_type = route_operation.x_station_type if route_operation else False
        return self.env['sn.wsd.mes.test.result'].ingest_meter_test_result(
            serial_number=serial_number,
            test_type=station_type if station_type in ('programming', 'inspection', 'aging', 'calibration', 'final_test', 'packaging') else 'final_test',
            result=result,
            workcenter_code=station_code,
            workorder_id=self.id,
            production_id=self.production_id.id,
            operator_code=operator_code,
            cycle_time_sec=cycle_time_sec,
            basic_error=basic_error,
            phase_error=phase_error,
            aging_temp_c=aging_temp_c,
            tester_channel=tester_channel,
            note=note,
            payload=payload,
            external_event_id=external_event_id,
            request_id=request_id,
            source_system=source_system,
            retry_sequence=retry_sequence,
            retry_limit=retry_limit,
            requires_repair=requires_repair,
            is_rework_pass=is_rework_pass,
            rework_source_workorder_id=rework_source_workorder_id,
        )
