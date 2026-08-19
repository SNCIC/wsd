from odoo import api, fields, models


class MesSnTravel(models.Model):
    _name = 'sn.wsd.mes.sn.travel'
    _description = 'MES SN Travel'
    _order = 'event_time desc, id desc'
    _inherit = 'sncic.mes.api.mixin'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    internal_serial_id = fields.Many2one('sn.wsd.internal.serial', string='Internal Serial', required=True, ondelete='cascade', index=True, check_company=True)
    product_id = fields.Many2one(related='internal_serial_id.product_id', store=True, index=True)
    production_id = fields.Many2one('mrp.production', ondelete='set null', index=True, check_company=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', ondelete='set null', index=True, check_company=True,
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
    event_type = fields.Selection(
        [('start', 'Start'), ('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold'), ('repair', 'Repair'), ('complete', 'Complete')],
        required=True, default='start', index=True,
    )
    event_time = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    operator_code = fields.Char(index=True)
    result = fields.Selection([('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold')], index=True)
    external_event_id = fields.Char(index=True)
    request_id = fields.Char(index=True)
    source_system = fields.Char(index=True)
    note = fields.Char()
    payload = fields.Json()
    retry_sequence = fields.Integer(string='Retry Sequence', default=0, index=True)
    retry_limit = fields.Integer(string='Retry Limit', default=0)
    requires_repair = fields.Boolean(string='Requires Repair', default=False, index=True)
    is_rework_pass = fields.Boolean(string='Rework Pass', default=False, index=True)

    @api.depends('internal_serial_id', 'workcenter_code', 'event_type', 'event_time')
    def _compute_name(self):
        for record in self:
            serial = record.internal_serial_id.serial_no or '-'
            station = record.workcenter_code or record.workcenter_id.code or '-'
            record.name = f'{serial} / {station} / {record.event_type}'

    @api.model
    def record_event(
        self,
        serial_number,
        event_type='start',
        workcenter_code=None,
        production_id=None,
        result=None,
        operator_code=None,
        note=None,
        payload=None,
        event_time=None,
        external_event_id=None,
        request_id=None,
        source_system=None,
        internal_serial_id=None,
        mes_order_id=None,
        route_operation_id=None,
        retry_sequence=0,
        retry_limit=0,
        requires_repair=False,
        is_rework_pass=False,
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
                    travel_id=existing.id,
                    serial_number=existing.internal_serial_id.serial_no,
                    mes_order_id=existing.mes_order_id.id,
                    route_operation_id=existing.route_operation_id.id,
                    workcenter_code=existing.workcenter_code,
                )
        equipment = self.env['sn.wsd.device.equipment'].browse(equipment_id).exists() if equipment_id else self.env['sn.wsd.device.equipment']
        workcenter = self.env['mrp.workcenter']
        route_operation = self.env['sn.wsd.mes.order.route.operation'].browse(route_operation_id).exists() if route_operation_id else self.env['sn.wsd.mes.order.route.operation']
        if workcenter_code:
            workcenter = workcenter.search([('code', '=', workcenter_code)], limit=1)
        mes_order = (
            self.env['sn.wsd.mes.order'].browse(mes_order_id or payload.get('mes_order_id')).exists()
            if (mes_order_id or payload.get('mes_order_id')) else False
        )
        if not mes_order and route_operation:
            mes_order = route_operation.mes_order_id
        production = self.env['mrp.production'].browse(production_id).exists() if production_id else mes_order.production_id
        if not mes_order and production:
            mes_order = production.x_mes_order_ids.filtered(
                lambda order: order.state != 'cancelled'
            )[:1]
        product = production.product_id or mes_order.product_id
        event_dt = fields.Datetime.to_datetime(event_time) if event_time else fields.Datetime.now()
        serial = self.env['sn.wsd.internal.serial'].browse(internal_serial_id).exists() if internal_serial_id else self.env['sn.wsd.internal.serial'].find_for_manufacturing_context(
            serial_number,
            company=production.company_id or mes_order.company_id or self.env.company,
            production=production,
            mes_order=mes_order,
            product=product,
        )
        if not serial:
            return self._mes_error('serial_not_found', serial_number=serial_number)
        production_line = workcenter.x_production_line_id
        workshop = workcenter.x_workshop_id
        line_code = production_line.code or False
        workcenter_code = workcenter.code or workcenter_code or False
        travel = self.create({
            'internal_serial_id': serial.id,
            'production_id': production.id if production else False,
            'mes_order_id': mes_order.id if mes_order else False,
            'route_operation_id': route_operation.id if route_operation else False,
            'workcenter_id': workcenter.id if workcenter else False,
            'workshop_id': workshop.id if workshop else False,
            'production_line_id': production_line.id if production_line else False,
            'equipment_id': equipment.id if equipment else False,
            'line_code': line_code,
            'workcenter_code': workcenter_code,
            'event_type': event_type,
            'event_time': event_dt,
            'operator_code': operator_code,
            'result': result,
            'external_event_id': external_event_id,
            'request_id': request_id,
            'source_system': source_system,
            'note': note,
            'payload': payload,
            'retry_sequence': retry_sequence,
            'retry_limit': retry_limit,
            'requires_repair': requires_repair,
            'is_rework_pass': is_rework_pass,
        })
        return self._mes_ok(
            duplicated=False,
            travel_id=travel.id,
            serial_number=serial.serial_no,
            mes_order_id=travel.mes_order_id.id,
            route_operation_id=travel.route_operation_id.id,
            workcenter_code=travel.workcenter_code,
        )

    @api.model
    def latest_event_by_serial(self, serial_number, internal_serial_id=None):
        serial = self.env['sn.wsd.internal.serial'].browse(internal_serial_id).exists() if internal_serial_id else self.env['sn.wsd.internal.serial'].find_for_manufacturing_context(serial_number)
        if not serial:
            return self._mes_error('serial_not_found', serial_number=serial_number)
        latest = self.search([('internal_serial_id', '=', serial.id)], order='event_time desc, id desc', limit=1)
        if not latest:
            return self._mes_ok(serial_number=serial.serial_no, latest_event=False)
        return self._mes_ok(serial_number=serial.serial_no, latest_event={
            'id': latest.id,
            'workcenter_code': latest.workcenter_code,
            'event_type': latest.event_type,
            'result': latest.result,
            'event_time': latest.event_time,
            'retry_sequence': latest.retry_sequence,
            'retry_limit': latest.retry_limit,
            'requires_repair': latest.requires_repair,
            'is_rework_pass': latest.is_rework_pass,
        })

    @api.model
    def serial_route_guard(self, serial_number, workcenter_code, override_allowed=False, internal_serial_id=None):
        return self._mes_error(
            'route_operation_not_found',
            station_code=workcenter_code,
            serial_number=serial_number,
        )
