from odoo import api, fields, models


class MesTestResultBase(models.Model):
    _name = 'sn.wsd.mes.test.result'
    _description = 'MES Test Result'
    _order = 'test_time desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN', required=True,
        ondelete='cascade', index=True, check_company=True)
    product_id = fields.Many2one('product.product', index=True)
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
    result = fields.Selection([('ok', 'OK'), ('ng', 'NG'), ('hold', 'Hold')], required=True, default='ok', index=True)
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
    # tooling trace field (design #6): non-key tooling SNs are recorded on
    # the pass result only; key-material tooling also counts via
    # register_usage
    tooling_sns = fields.Char(
        string='Tooling SNs', index=True,
        help='Tooling SNs (M_TOOLING) recorded with this pass.')
    equipment_sn = fields.Char(
        string='Equipment SN', index=True,
        help='Device SN (M_DEVICE_SN) that performed this test.')

    detail_ids = fields.One2many(
        'sn.wsd.mes.test.result.detail', 'test_result_id', string='Test Items')
    retry_sequence = fields.Integer(string='Retry Sequence', default=0, index=True)
    retry_limit = fields.Integer(string='Retry Limit', default=0)
    requires_repair = fields.Boolean(string='Requires Repair', default=False, index=True)
    is_rework_pass = fields.Boolean(string='Rework Pass', default=False, index=True)

    @api.depends('serial_identity_id', 'test_type', 'test_time')
    def _compute_name(self):
        for record in self:
            serial = record.serial_identity_id.name or '-'
            record.name = f'{serial} / {record.test_type}'

    @api.model
    def ingest_meter_test_result(
        self,
        serial_number,
        test_type='final_test',
        result='ok',
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
        equipment_id=None,
    ):
        """Ingest one device test result. Kept as the landing model for the
        future device API; the serial is resolved against the identity
        registry directly (the stage-archive registry is gone)."""
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
                return {
                    'ok': True,
                    'duplicated': True,
                    'test_result_id': existing.id,
                    'serial_number': existing.serial_identity_id.name,
                    'result': existing.result,
                }
        equipment = self.env['sn.wsd.device.equipment'].browse(equipment_id).exists() if equipment_id else self.env['sn.wsd.device.equipment']
        workcenter = self.env['mrp.workcenter']
        route_operation = self.env['sn.wsd.mes.order.route.operation'].browse(route_operation_id).exists() if route_operation_id else self.env['sn.wsd.mes.order.route.operation']
        mes_order = self.env['sn.wsd.mes.order'].browse(mes_order_id or payload.get('mes_order_id')).exists() if (mes_order_id or payload.get('mes_order_id')) else self.env['sn.wsd.mes.order']
        if route_operation and not mes_order:
            mes_order = route_operation.mes_order_id
        if workcenter_code:
            workcenter = workcenter.search([('code', '=', workcenter_code)], limit=1)
        production = self.env['mrp.production'].browse(production_id).exists() if production_id else mes_order.production_id
        company = production.company_id or mes_order.company_id or self.env.company
        identity = self.env['sn.wsd.serial.identity'].get_or_create(
            (serial_number or '').strip(), company, origin_type='external')
        if not mes_order:
            wip = self.env['sn.wsd.serial.wip'].search(
                [('serial_identity_id', '=', identity.id)], limit=1)
            mes_order = wip.mes_order_id if wip else mes_order
        test_dt = fields.Datetime.to_datetime(test_time) if test_time else fields.Datetime.now()
        production_line = workcenter.x_production_line_id
        workshop = workcenter.x_workshop_id
        vals = {
            'serial_identity_id': identity.id,
            'product_id': production.product_id.id if production else False,
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
            'tooling_sns': payload.get('M_TOOLING', ''),
            'equipment_sn': payload.get('M_DEVICE_SN', ''),
            'retry_sequence': retry_sequence,
            'retry_limit': retry_limit,
            'requires_repair': requires_repair,
            'is_rework_pass': is_rework_pass,
        }
        raw_defect = (payload.get('M_STR2') or '').strip()
        if raw_defect and result == 'ng' and 'defect_code_id' in self._fields:
            # link the quality dictionary when installed (terminal NG flow
            # uses the same field)
            defect = self.env['sn.wsd.quality.defect.code'].search([
                '|', ('code', '=ilike', raw_defect),
                ('name', '=ilike', raw_defect),
                ('company_id', 'in', [company.id, False]),
            ], limit=1)
            vals['defect_code_id'] = defect.id
        record = self.create(vals)
        self.env['sn.wsd.mes.test.result.detail'].create_from_test_result(
            record, payload.get('M_TEST_DETAIL'))
        return {
            'ok': True,
            'duplicated': False,
            'test_result_id': record.id,
            'serial_number': identity.name,
            'result': record.result,
        }
