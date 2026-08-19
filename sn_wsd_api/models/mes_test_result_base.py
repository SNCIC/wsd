import json

from odoo import api, fields, models


class MesTestResultBase(models.Model):
    _name = 'sn.wsd.mes.test.result'
    _description = 'MES Test Result'
    _order = 'test_time desc, id desc'
    _inherit = 'sncic.mes.api.mixin'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    internal_serial_id = fields.Many2one('sn.wsd.internal.serial', string='Internal Serial', required=True, ondelete='cascade', index=True, check_company=True)
    product_id = fields.Many2one(related='internal_serial_id.product_id', store=True, index=True)
    production_id = fields.Many2one('mrp.production', ondelete='set null', index=True, check_company=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='MES Route Operation',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    workcenter_id = fields.Many2one('mrp.workcenter', string='MES Work Center', ondelete='set null', index=True, check_company=True)
    workshop_id = fields.Many2one('sn.mrp.workshop', ondelete='set null', index=True, check_company=True)
    production_line_id = fields.Many2one('sn.mrp.production.line', ondelete='set null', index=True, check_company=True)
    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment',
        ondelete='set null',
        index=True,
    )
    line_code = fields.Char(index=True)
    workcenter_code = fields.Char(index=True)
    test_type = fields.Selection(
        [('programming', 'Programming'), ('inspection', 'Inspection'), ('aging', 'Aging'), ('calibration', 'Calibration'), ('final_test', 'Final Test'), ('packaging', 'Packaging')],
        required=True, default='final_test', index=True,
    )
    test_time = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    result = fields.Selection([('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold')], required=True, default='pass', index=True)
    cycle_time_sec = fields.Float()
    operator_code = fields.Char(index=True)
    tester_channel = fields.Char()
    external_event_id = fields.Char(index=True)
    request_id = fields.Char(index=True)
    source_system = fields.Char(index=True)
    basic_error = fields.Float()
    phase_error = fields.Float()
    aging_temp_c = fields.Float()
    payload = fields.Json()
    note = fields.Char()
    travel_id = fields.Many2one('sn.wsd.mes.sn.travel', ondelete='set null', index=True, check_company=True)
    retry_sequence = fields.Integer(string='Retry Sequence', default=0, index=True)
    retry_limit = fields.Integer(string='Retry Limit', default=0)
    requires_repair = fields.Boolean(string='Requires Repair', default=False, index=True)
    is_rework_pass = fields.Boolean(string='Rework Pass', default=False, index=True)

    @api.depends('internal_serial_id', 'test_type', 'test_time')
    def _compute_name(self):
        for record in self:
            serial = record.internal_serial_id.serial_no or '-'
            record.name = f'{serial} / {record.test_type}'

    @api.model
    def ingest_meter_test_result(
        self,
        serial_number,
        test_type='final_test',
        result='pass',
        workcenter_code=None,
        production_id=None,
        operator_code=None,
        cycle_time_sec=None,
        basic_error=None,
        phase_error=None,
        aging_temp_c=None,
        tester_channel=None,
        note=None,
        payload=None,
        test_time=None,
        external_event_id=None,
        request_id=None,
        source_system=None,
        retry_sequence=0,
        retry_limit=0,
        requires_repair=False,
        is_rework_pass=False,
        mes_order_id=None,
        route_operation_id=None,
        travel_event_type=None,
        travel_result=None,
        equipment_id=None,
    ):
        payload = payload or {}
        external_event_id = external_event_id or payload.get('external_event_id') or payload.get('event_id') or False
        request_id = request_id or False
        source_system = source_system or payload.get('source_system') or False
        if external_event_id:
            existing_domain = [('external_event_id', '=', external_event_id)]
            if source_system:
                existing_domain.append(('source_system', '=', source_system))
            existing = self.search(existing_domain, limit=1)
            if existing:
                return self._mes_ok(
                    duplicated=True,
                    test_result_id=existing.id,
                    travel_id=existing.travel_id.id if existing.travel_id else False,
                    serial_number=existing.internal_serial_id.serial_no,
                    result=existing.result,
                )
        equipment = self.env['sn.wsd.device.equipment'].browse(equipment_id).exists() if equipment_id else self.env['sn.wsd.device.equipment']
        workcenter = self.env['mrp.workcenter']
        route_operation = self.env['sn.wsd.mes.order.route.operation'].browse(route_operation_id).exists() if route_operation_id else self.env['sn.wsd.mes.order.route.operation']
        mes_order = self.env['sn.wsd.mes.order'].browse(mes_order_id or payload.get('mes_order_id')).exists() if (mes_order_id or payload.get('mes_order_id')) else self.env['sn.wsd.mes.order']
        if route_operation and not mes_order:
            mes_order = route_operation.mes_order_id
        if workcenter_code:
            workcenter = workcenter.search([('code', '=', workcenter_code)], limit=1)
        production = self.env['mrp.production'].browse(production_id).exists() if production_id else mes_order.production_id
        if not production and mes_order:
            production = mes_order.production_id
        serial = self.env['sn.wsd.internal.serial'].find_for_manufacturing_context(
            serial_number,
            company=production.company_id or mes_order.company_id or self.env.company,
            production=production,
            mes_order=mes_order,
            product=production.product_id or mes_order.product_id,
        )
        if not serial:
            return self._mes_error('serial_not_found', serial_number=serial_number)
        mes_order = mes_order or serial.mes_order_id
        test_dt = fields.Datetime.to_datetime(test_time) if test_time else fields.Datetime.now()
        travel_result = travel_result or (
            'pass' if result == 'pass' else 'fail' if result == 'fail' else 'hold'
        )
        production_line = workcenter.x_production_line_id
        workshop = workcenter.x_workshop_id
        travel = self.env['sn.wsd.mes.sn.travel'].record_event(
            serial_number=serial_number,
            event_type=travel_event_type or ('pass' if result == 'pass' else 'fail'),
            workcenter_code=workcenter_code,
            production_id=production.id if production else False,
            result=travel_result,
            operator_code=operator_code,
            note=note,
            payload=payload,
            event_time=test_dt,
            external_event_id=external_event_id,
            request_id=request_id,
            source_system=source_system,
            mes_order_id=mes_order.id if mes_order else False,
            route_operation_id=route_operation.id if route_operation else False,
            equipment_id=equipment.id if equipment else False,
            retry_sequence=retry_sequence,
            retry_limit=retry_limit,
            requires_repair=requires_repair,
            is_rework_pass=is_rework_pass,
        )
        if isinstance(travel, dict) and travel.get('error'):
            return travel
        travel_id = travel.get('travel_id') if isinstance(travel, dict) else False
        record = self.create({
            'internal_serial_id': serial.id,
            'production_id': production.id if production else False,
            'mes_order_id': mes_order.id if mes_order else False,
            'route_operation_id': route_operation.id if route_operation else False,
            'workcenter_id': workcenter.id if workcenter else False,
            'workshop_id': workshop.id if workshop else False,
            'production_line_id': production_line.id if production_line else False,
            'equipment_id': equipment.id if equipment else False,
            'line_code': production_line.code or False,
            'workcenter_code': workcenter.code or workcenter_code or False,
            'test_type': test_type,
            'test_time': test_dt,
            'result': result,
            'cycle_time_sec': cycle_time_sec,
            'operator_code': operator_code,
            'tester_channel': tester_channel,
            'external_event_id': external_event_id,
            'request_id': request_id,
            'source_system': source_system,
            'basic_error': basic_error,
            'phase_error': phase_error,
            'aging_temp_c': aging_temp_c,
            'payload': payload,
            'note': note,
            'travel_id': travel_id,
            'retry_sequence': retry_sequence,
            'retry_limit': retry_limit,
            'requires_repair': requires_repair,
            'is_rework_pass': is_rework_pass,
        })
        return self._mes_ok(
            duplicated=False,
            test_result_id=record.id,
            travel_id=travel_id,
            serial_number=serial.serial_no,
            result=record.result,
        )
