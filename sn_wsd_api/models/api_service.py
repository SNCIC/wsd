import json
import uuid
from datetime import datetime
from datetime import timezone

from odoo import api, fields, models
from odoo.exceptions import AccessDenied
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError


MSG_SAVE_SUCCESS = '\u4fdd\u5b58\u6210\u529f'
MSG_QUERY_SUCCESS = '\u67e5\u8be2\u6210\u529f'
MSG_PARAM_EMPTY = '\u53c2\u6570\u4e0d\u80fd\u4e3a\u7a7a'
MSG_USER_INVALID = '\u7528\u6237\u4e0d\u5b58\u5728\u6216\u5bc6\u7801\u9519\u8bef'
MSG_ORG_INVALID = '\u7ec4\u7ec7\u4e0d\u5b58\u5728'
MSG_USER_ORG_INVALID = '\u7528\u6237\u4e0d\u5c5e\u4e8e\u8be5\u7ec4\u7ec7'


class SnWsdApiService(models.AbstractModel):
    _name = 'sn.wsd.api.service'
    _description = 'WSD Public JSON-2 API Service'

    _AOI_REQUIRED_FIELDS = (
        'productSn',
        'machineName',
        'retestResult',
        'stationResult',
        'stationInfo',
        'testTime',
        'createTime',
        'operator',
    )
    _LASER_REQUIRED_FIELDS = (
        'workOrderNo',
        'quantity',
    )

    @api.model
    def _resolve_scan_external_event_id(self, payload):
        return (
            self._get_first_payload_value(payload, 'M_EVENT_ID')
            or f'scan-pass:{uuid.uuid4().hex}'
        )

    @api.model
    def _service_ok(self, data: dict) -> dict:
        return {
            'ok': True,
            'data': data,
            'error': False,
        }

    @api.model
    def _service_error(self, code: str, message: str, **details) -> dict:
        return {
            'ok': False,
            'data': False,
            'error': {
                'code': code,
                'message': message,
                'details': details or {},
            },
        }

    @api.model
    def _normalize_mes_result(self, result: dict) -> dict:
        if result.get('ok'):
            data = {
                key: value
                for key, value in result.items()
                if key != 'ok'
            }
            return self._service_ok(data)
        return self._service_error(
            result.get('error', 'unknown_error'),
            result.get('message') or result.get('error', 'unknown_error'),
            **{
                key: value
                for key, value in result.items()
                if key not in ('ok', 'error', 'message')
            },
        )

    @api.model
    def _prepare_payload_metadata(
        self,
        payload: dict | None = None,
        external_event_id: str | None = None,
        source_system: str | None = None,
    ) -> dict:
        payload = dict(payload or {})
        if external_event_id:
            payload['external_event_id'] = external_event_id
        if source_system:
            payload['source_system'] = source_system
        return payload

    @api.model
    def _aoi_response(self, code: int = 200, message: str = 'success', data: dict | None = None) -> dict:
        return {
            'code': code,
            'message': message,
            'data': data or {},
        }

    @api.model
    def _aoi_error(self, message: str, **data) -> dict:
        return self._aoi_response(code=400, message=message, data=data)

    @api.model
    def _laser_error(self, message: str) -> dict:
        return {
            'code': 400,
            'message': message,
        }

    @api.model
    def _strict_external_error(self, message: str) -> dict:
        return {
            'code': 400,
            'message': message,
        }

    @api.model
    def _external_response(self, code: int = 200, message: str = 'success', data=None) -> dict:
        response = {
            'code': code,
            'message': message,
        }
        if data is not None:
            response['data'] = data
        return response

    @api.model
    def _external_success(self, data=None, message: str = MSG_QUERY_SUCCESS) -> dict:
        return self._external_response(code=200, message=message, data=data)

    @api.model
    def _external_error(self, message: str, data=None, code: int = 400) -> dict:
        return self._external_response(code=code, message=message, data=data)

    @api.model
    def _get_payload_value(self, payload: dict | None, field_name: str):
        if not isinstance(payload, dict):
            return False
        value = payload.get(field_name)
        return value.strip() if isinstance(value, str) else value

    @api.model
    def _get_first_payload_value(self, payload: dict | None, *field_names):
        for field_name in field_names:
            value = self._get_payload_value(payload, field_name)
            if value not in (None, ''):
                return value
        return False

    @api.model
    def _scan_payload_value(self, payload: dict | None, field_name: str):
        return self._get_payload_value(payload, field_name)

    @api.model
    def _get_mes_order_no(self, payload: dict | None):
        return self._get_first_payload_value(
            payload,
            'workOrderNo',
            'work_order_no',
            'manufacturingOrderNo',
            'manufacturing_order_no',
            'M_MO_NUMBER',
        )

    @api.model
    def _find_mes_order(self, order_no: str | None):
        if not order_no:
            return self.env['sn.wsd.mes.order']
        return self.env['sn.wsd.mes.order'].sudo().search([
            ('name', '=', order_no),
            ('company_id', 'in', self.env.companies.ids),
        ], limit=1)

    @api.model
    def _select_mes_order_production(self, mes_order, *, workcenter=False, smt_required=False, meter_required=False):
        if not mes_order:
            return self.env['mrp.production']
        candidates = mes_order.production_id.filtered(lambda production: production.state not in ('done', 'cancel'))
        if smt_required:
            candidates = candidates.filtered('x_has_smt_operations')
        if meter_required:
            candidates = candidates.filtered('x_has_meter_operations')
        if workcenter:
            candidates = candidates.filtered(
                lambda production: any(
                    workorder.state not in ('done', 'cancel')
                    and workcenter in (workorder.x_mes_workcenter_id | workorder.workcenter_id)
                    for workorder in production.workorder_ids
                )
            )
        online = candidates._has_online_mes_order()
        if online:
            candidates = online
        in_progress = candidates.filtered(lambda production: production.state in ('progress', 'to_close'))
        if in_progress:
            candidates = in_progress
        return candidates.sorted(lambda production: (production.backorder_sequence, production.date_start or fields.Datetime.now(), production.id))[:1]

    @api.model
    def _find_production_by_mes_order_no(self, order_no: str | None, *, smt_required=False, meter_required=False):
        mes_order = self._find_mes_order(order_no)
        return self._select_mes_order_production(
            mes_order,
            smt_required=smt_required,
            meter_required=meter_required,
        ) if mes_order else self.env['mrp.production']

    @api.model
    def _scan_company_from_payload(self, payload: dict | None):
        company_value = self._scan_payload_value(payload, 'M_DATA_AUTH')
        if not company_value:
            return self.env['res.company'], self._aoi_error('Organization is empty.', error_code='organization_empty')
        try:
            company_id = int(company_value)
        except (TypeError, ValueError):
            company_id = 0
        if company_id:
            company_domain = ['|', ('id', '=', company_id), ('company_registry', '=', company_value)]
        else:
            company_domain = [('company_registry', '=', company_value)]
        company = self.env['res.company'].sudo().with_context(active_test=False).search(company_domain, limit=1)
        if not company:
            return company, self._aoi_error('Organization does not exist.', error_code='organization_not_found', M_DATA_AUTH=company_value)
        if company.id not in self.env.companies.ids:
            return company, self._aoi_error('Organization is not allowed.', error_code='organization_not_allowed', M_DATA_AUTH=company_value)
        return company, False

    @api.model
    def _scan_validate_employee(self, user_login: str | None, company):
        if not user_login:
            return self._aoi_error('User login is empty.', error_code='user_login_empty')
        user = self.env['res.users'].sudo().with_context(active_test=False).search([
            ('login', '=', user_login),
        ], limit=1)
        if user and company in user.company_ids:
            return False
        return self._aoi_error(
            'User login does not exist in MES.',
            error_code='user_login_not_found',
            M_EMP=user_login,
        )

    @api.model
    def _validate_scan_required_context(self, payload: dict | None):
        company, company_error = self._scan_company_from_payload(payload)
        if company_error:
            return company, company_error
        employee_error = self._scan_validate_employee(self._scan_payload_value(payload, 'M_EMP'), company)
        if employee_error:
            return company, employee_error
        return company, False

    @api.model
    def external_login_check(self, payload: dict) -> dict:
        login = self._get_payload_value(payload, 'userName')
        password = self._get_payload_value(payload, 'password')
        organization = self._get_payload_value(payload, 'organization')
        if not login or not password:
            return self._external_error(MSG_PARAM_EMPTY)

        credential = {
            'login': login,
            'password': password,
            'type': 'password',
        }
        try:
            auth_info = self.env['res.users'].sudo().authenticate(credential, {'interactive': False})
        except AccessDenied:
            return self._external_error(MSG_USER_INVALID, code=401)

        user = self.env['res.users'].sudo().browse(auth_info.get('uid')).exists()
        if not user:
            return self._external_error(MSG_USER_INVALID, code=401)
        if organization:
            try:
                company_id = int(organization)
            except (TypeError, ValueError):
                return self._external_error(MSG_ORG_INVALID, code=404)
            company = self.env['res.company'].sudo().browse(company_id).exists()
            if not company:
                return self._external_error(MSG_ORG_INVALID, code=404)
            if company_id not in user.company_ids.ids:
                return self._external_error(MSG_USER_ORG_INVALID, code=403)
        return self._external_response(code=200, message=MSG_SAVE_SUCCESS)

    @api.model
    def get_productions_by_work_order(self, payload: dict) -> dict:
        order_keyword = (
            self._get_payload_value(payload, 'keyword')
            or self._get_payload_value(payload, 'manufacturing_order_keyword')
            or self._get_payload_value(payload, 'manufacturingOrderKeyword')
            or self._get_payload_value(payload, 'manufacturing_order_no')
            or self._get_payload_value(payload, 'manufacturingOrderNo')
            or self._get_payload_value(payload, 'work_order')
        )
        if not order_keyword:
            return self._external_error(MSG_PARAM_EMPTY, data=[])
        orders = self.env['sn.wsd.mes.order'].sudo().search([
            ('name', 'ilike', order_keyword),
            ('company_id', 'in', self.env.companies.ids),
        ], order='create_date desc, id desc', limit=50)
        return self._external_success(data=orders.mapped('name'))

    @api.model
    def get_workcenters_by_name(self, payload: dict) -> dict:
        work_station = self._get_payload_value(payload, 'work_station')
        if not work_station:
            return self._external_error(MSG_PARAM_EMPTY, data=[])
        workcenters = self.env['mrp.workcenter'].sudo().with_context(active_test=False).search([
            '|',
            ('name', 'ilike', work_station),
            ('code', 'ilike', work_station),
        ], order='sequence asc, code asc, id asc', limit=50)
        data = [[workcenter.code or '', workcenter.name or ''] for workcenter in workcenters]
        return self._external_success(data=data)

    @api.model
    def get_defect_codes_by_name(self, payload: dict) -> dict:
        err_name = self._get_payload_value(payload, 'err_name')
        if not err_name:
            return self._external_error(MSG_PARAM_EMPTY, data=[])
        if not self.env.registry.get('sn.wsd.quality.defect.code'):
            return self._external_success(data=[])
        defect_codes = self.env['sn.wsd.quality.defect.code'].sudo().with_context(active_test=False).search([
            '|',
            ('name', 'ilike', err_name),
            ('code', 'ilike', err_name),
        ], order='code asc, id asc', limit=50)
        data = [[defect.code or '', defect.name or ''] for defect in defect_codes]
        return self._external_success(data=data)

    @api.model
    def _validate_laser_payload(self, payload: dict) -> str | None:
        if not isinstance(payload, dict):
            return 'Payload must be a JSON object.'
        for field_name in self._LASER_REQUIRED_FIELDS:
            if payload.get(field_name) in (None, ''):
                return f'Missing required field: {field_name}'
        try:
            quantity = int(payload.get('quantity'))
        except (TypeError, ValueError):
            return 'Field quantity must be an integer.'
        if quantity <= 0:
            return 'Field quantity must be greater than zero.'
        return None

    @api.model
    def _normalize_laser_payload(self, payload: dict) -> dict:
        source_payload = payload if isinstance(payload, dict) else {}
        normalized = {}
        work_order_no = self._get_payload_value(source_payload, 'workOrderNo')
        quantity = self._get_payload_value(source_payload, 'quantity')
        drawing_no = self._get_payload_value(source_payload, 'drawingNo')
        operator_code = self._get_payload_value(source_payload, 'operator')
        if work_order_no:
            normalized['workOrderNo'] = work_order_no
        if quantity not in (None, ''):
            normalized['quantity'] = quantity
        if drawing_no:
            normalized['drawingNo'] = drawing_no
        if operator_code:
            normalized['operator'] = operator_code
        return normalized

    @api.model
    def _find_laser_production(self, work_order_no: str):
        return self._find_production_by_mes_order_no(work_order_no)

    @api.model
    def _prepare_laser_record_response_data(self, record, duplicated=False) -> dict:
        return {
            'productSnList': record.line_ids.mapped('serial_no'),
        }

    @api.model
    def submit_laser_print_request(
        self,
        payload: dict,
        source_system: str | None = 'LASER',
    ) -> dict:
        payload = self._normalize_laser_payload(payload)
        validation_error = self._validate_laser_payload(payload)
        if validation_error:
            return self._laser_error(validation_error)

        work_order_no = payload.get('workOrderNo')
        production = self._find_laser_production(work_order_no)
        if not production:
            return self._laser_error('MES order not found.')

        metadata_payload = self._prepare_payload_metadata(
            payload=payload,
            external_event_id=False,
            source_system=source_system,
        )
        try:
            result = production.api_request_laser_print(
                quantity=int(payload.get('quantity')),
                drawing_no=payload.get('drawingNo'),
                operator_code=payload.get('operator'),
                request_id=False,
                source_system=source_system,
                payload=metadata_payload,
                sn_scope=False,
            )
        except (UserError, ValidationError) as error:
            return self._laser_error(str(error))

        return self._aoi_response(data={
            'productSnList': result.get('serial_numbers') or [],
        })

    @api.model
    def _validate_aoi_payload(self, payload: dict) -> str | None:
        if not isinstance(payload, dict):
            return 'Payload must be a JSON object.'
        for field_name in self._AOI_REQUIRED_FIELDS:
            if payload.get(field_name) in (None, ''):
                return f'Missing required field: {field_name}'
        defect_details = payload.get('defectDetails') or []
        if not isinstance(defect_details, list):
            return 'Field defectDetails must be an array.'
        for index, detail in enumerate(defect_details, start=1):
            if not isinstance(detail, dict):
                return f'Defect detail #{index} must be a JSON object.'
            for field_name in ('defectCode', 'defectName', 'confirmedResult'):
                if detail.get(field_name) in (None, ''):
                    return f'Missing required field in defect detail #{index}: {field_name}'
        return None

    @api.model
    def _normalize_aoi_payload(self, payload: dict) -> dict:
        source_payload = payload if isinstance(payload, dict) else {}
        field_names = (
            'productSn',
            'logCode',
            'machineName',
            'type',
            'retestResult',
            'stationResult',
            'stationInfo',
            'testTime',
            'retestTime',
            'createTime',
            'fileName',
            'programName',
            'smallBoardNo',
            'totalParts',
            'errorParts',
            'confirmedDefectParts',
            'face',
            'operator',
            'defectDetails',
        )
        normalized = {}
        for field_name in field_names:
            value = source_payload.get(field_name)
            if isinstance(value, str):
                value = value.strip()
            if value not in (None, ''):
                normalized[field_name] = value
        if 'defectDetails' not in normalized:
            normalized['defectDetails'] = []
        return normalized

    @api.model
    def _normalize_aoi_result(self, station_result: str | None, retest_result: str | None = None) -> str:
        value = (station_result or retest_result or '').strip().lower()
        if value in ('ok', 'pass', 'passed', 'success', 'true', '1'):
            return 'pass'
        if value in ('hold', 'pending'):
            return 'hold'
        return 'fail'

    @api.model
    def _aoi_parse_datetime(self, value, field_name: str):
        try:
            return fields.Datetime.to_datetime(value)
        except Exception:
            pass
        try:
            normalized_value = value.strip() if isinstance(value, str) else value
            if isinstance(normalized_value, str) and normalized_value.endswith('Z'):
                normalized_value = f'{normalized_value[:-1]}+00:00'
            parsed_value = datetime.fromisoformat(normalized_value)
            if parsed_value.tzinfo:
                parsed_value = parsed_value.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed_value
        except Exception:
            raise ValueError(f'Invalid datetime field: {field_name}')

    @api.model
    def _find_aoi_equipment_and_workcenter(self, machine_name: str):
        equipment = self.env['maintenance.equipment'].search([('name', '=', machine_name)], limit=1)
        workcenter = equipment.x_mes_workcenter_id if equipment and equipment.x_mes_workcenter_id else self.env['mrp.workcenter']
        if not workcenter:
            workcenter = self.env['mrp.workcenter'].search([
                '|',
                ('name', '=', machine_name),
                ('code', '=', machine_name),
            ], limit=1)
        return equipment, workcenter

    @api.model
    def _find_aoi_workorder(self, workcenter, workorder_id: int | None = None):
        if workorder_id:
            return self.env['mrp.workorder'].browse(workorder_id).exists()
        if not workcenter:
            return self.env['mrp.workorder']
        base_domain = [
            ('state', 'in', ['ready', 'progress']),
            '|',
            ('x_mes_workcenter_id', '=', workcenter.id),
            ('workcenter_id', '=', workcenter.id),
        ]
        for extra_domain in (
            [('x_meter_operation_type', '=', 'aoi'), ('state', '=', 'progress')],
            [('x_meter_operation_type', '=', 'aoi')],
            [('state', '=', 'progress')],
            [],
        ):
            workorder = self.env['mrp.workorder'].search(
                base_domain + extra_domain,
                order='date_start asc, sequence asc, id asc',
                limit=1,
            )
            if workorder:
                return workorder
        return self.env['mrp.workorder']

    @api.model
    def _prepare_aoi_result_values(self, payload: dict) -> dict:
        return {
            'aoi_log_code': payload.get('logCode'),
            'aoi_machine_name': payload.get('machineName'),
            'aoi_inspection_type': payload.get('type'),
            'aoi_retest_result': payload.get('retestResult'),
            'aoi_station_result': payload.get('stationResult'),
            'aoi_station_info': payload.get('stationInfo'),
            'aoi_retest_time': self._aoi_parse_datetime(payload['retestTime'], 'retestTime')
            if payload.get('retestTime') else False,
            'aoi_create_time': self._aoi_parse_datetime(payload['createTime'], 'createTime')
            if payload.get('createTime') else False,
            'aoi_file_name': payload.get('fileName'),
            'aoi_program_name': payload.get('programName'),
            'aoi_small_board_no': payload.get('smallBoardNo'),
            'aoi_total_parts': payload.get('totalParts') or 0,
            'aoi_error_parts': payload.get('errorParts') or 0,
            'aoi_confirmed_defect_parts': payload.get('confirmedDefectParts') or 0,
            'aoi_face': payload.get('face'),
            'aoi_operator': payload.get('operator'),
        }

    @api.model
    def _create_aoi_defect_details(self, test_result, payload: dict):
        details = payload.get('defectDetails') or []
        if not test_result or not details:
            return self.env['sn.wsd.aoi.defect.detail']
        values = []
        for detail in details:
            values.append({
                'company_id': test_result.company_id.id,
                'test_result_id': test_result.id,
                'part_id': detail.get('partId'),
                'position': detail.get('position'),
                'defect_code': detail.get('defectCode'),
                'defect_name': detail.get('defectName'),
                'confirmed_result': detail.get('confirmedResult'),
                'image_path': detail.get('imagePath'),
                'payload': detail,
            })
        return self.env['sn.wsd.aoi.defect.detail'].create(values)

    @api.model
    def submit_aoi_result(
        self,
        payload: dict,
        workorder_id: int | None = None,
        source_system: str | None = 'AOI',
        override_route: bool = False,
    ) -> dict:
        payload = self._normalize_aoi_payload(payload)
        validation_error = self._validate_aoi_payload(payload)
        if validation_error:
            return self._strict_external_error(validation_error)

        product_sn = payload.get('productSn')
        machine_name = payload.get('machineName')
        external_event_id = payload.get('logCode') or f"aoi:{machine_name}:{product_sn}:{payload.get('testTime')}"

        try:
            test_time = self._aoi_parse_datetime(payload.get('testTime'), 'testTime')
            self._aoi_parse_datetime(payload.get('createTime'), 'createTime')
            if payload.get('retestTime'):
                self._aoi_parse_datetime(payload.get('retestTime'), 'retestTime')
        except ValueError as error:
            return self._strict_external_error(str(error))

        equipment, workcenter = self._find_aoi_equipment_and_workcenter(machine_name)
        if not workcenter:
            return self._strict_external_error('Machine is not bound to a work center.')

        workorder = self._find_aoi_workorder(workcenter, workorder_id=workorder_id)
        if not workorder:
            return self._strict_external_error('Active AOI work order not found.')

        serial, serial_error = self._validate_serial_for_workorder(product_sn, workorder)
        if serial_error:
            return self._strict_external_error(serial_error.get('message') or 'Serial validation failed.')

        if hasattr(workorder, '_mes_validate_execution'):
            route_validation = workorder._mes_validate_execution(
                serial_number=product_sn,
                allow_restart=True,
                override_route=override_route,
            )
            if route_validation.get('error'):
                return self._strict_external_error(route_validation.get('message') or route_validation.get('error'))

        result = self._normalize_aoi_result(payload.get('stationResult'), payload.get('retestResult'))
        metadata_payload = self._prepare_payload_metadata(
            payload=payload,
            external_event_id=external_event_id,
            source_system=source_system,
        )
        ingest_result = self.env['sn.wsd.mes.test.result'].ingest_meter_test_result(
            serial_number=product_sn,
            test_type='aoi',
            result=result,
            workcenter_code=workcenter.code,
            workorder_id=workorder.id,
            production_id=workorder.production_id.id,
            operator_code=payload.get('operator'),
            tester_channel=payload.get('fileName'),
            note=payload.get('stationInfo'),
            payload=metadata_payload,
            test_time=test_time,
            external_event_id=external_event_id,
            request_id=False,
            source_system=source_system,
        )
        if ingest_result.get('error'):
            return self._strict_external_error(ingest_result.get('message') or ingest_result.get('error'))

        test_result = self.env['sn.wsd.mes.test.result'].browse(ingest_result.get('test_result_id')).exists()
        created_details = self.env['sn.wsd.aoi.defect.detail']
        if test_result and not ingest_result.get('duplicated'):
            test_result.write(self._prepare_aoi_result_values(metadata_payload))
            created_details = self._create_aoi_defect_details(test_result, metadata_payload)
            if test_result.workorder_id and hasattr(test_result.workorder_id, 'action_register_terminal_report'):
                report = self.env['mrp.workorder.report'].search([
                    ('company_id', '=', test_result.company_id.id),
                    ('external_event_id', '=', external_event_id),
                ], limit=1)

        return self._aoi_response(data={})

    @api.model
    def _get_panel_model(self):
        return self.env['sn.smt.pcb.panel'].sudo()

    @api.model
    def _get_panel_api_model(self):
        return self.env['sn.smt.pcb.panel.api'].sudo()

    @api.model
    def _panel_response(self, panel):
        return panel.to_api_response()

    @api.model
    def add_panel(self, payload: dict) -> dict:
        result = self._get_panel_api_model().api_panel_add(payload)
        return result

    @api.model
    def query_panels(self, payload: dict) -> dict:
        result = self._get_panel_api_model().api_panel_query(payload)
        if result.get('code', 400) >= 400:
            return result
        return self._external_success(data=result.get('data') or [])

    @api.model
    def delete_panel(self, payload: dict) -> dict:
        panel_id = self._get_payload_value(payload, 'panelId')
        if panel_id in (None, ''):
            return self._external_error(MSG_PARAM_EMPTY, data={'fields': ['panelId']})
        try:
            panel_id = int(panel_id)
        except (TypeError, ValueError):
            return self._external_error('Field panelId must be an integer.')
        panel = self._get_panel_model().browse(panel_id).exists()
        if not panel:
            return self._external_error('Panel record does not exist.', data={'panelId': panel_id})
        return self._get_panel_api_model().api_panel_delete(panel_id)

    @api.model
    def get_current_online_context(
        self,
        workcenter_id: int | None = None,
        production_line_id: int | None = None,
        workshop_id: int | None = None,
    ) -> dict:
        """
        Get the current online manufacturing and work order context.

        This method is intended for workshop terminals, barcode clients,
        or integration gateways that need to know which manufacturing
        order and work order are currently active for a station scope.

        :param workcenter_id: MES work center ID used to derive the online scope.
        :param production_line_id: Production line ID when work center is not provided.
        :param workshop_id: Workshop ID when only workshop-level scope is known.
        :returns: A standard API payload containing the resolved production and work order.
        """
        workcenter = self.env['mrp.workcenter'].browse(workcenter_id).exists() if workcenter_id else self.env['mrp.workcenter']
        production_line = self.env['sn.mrp.production.line'].browse(production_line_id).exists() if production_line_id else workcenter.x_production_line_id
        workshop = self.env['sn.mrp.workshop'].browse(workshop_id).exists() if workshop_id else workcenter.x_workshop_id or production_line.workshop_id
        production = self.env['mrp.production']._get_current_online_production(
            workcenter=workcenter,
            production_line=production_line,
            workshop=workshop,
        )
        if not production:
            return self._service_ok({
                'mes_order': False,
                'production': False,
                'workorder': False,
            })
        workorder = production._get_current_online_workorder(workcenter=workcenter)
        mes_order = production.x_mes_order_ids.filtered(
            lambda order: order.state not in ('cancelled', 'done')
        )[:1]
        return self._service_ok({
            'mes_order': {
                'id': mes_order.id,
                'name': mes_order.name,
                'product_id': mes_order.product_id.id,
                'product_name': mes_order.product_id.display_name,
                'planned_qty': mes_order.planned_qty,
                'state': mes_order.state,
            } if mes_order else False,
            'production': {
                'id': production.id,
                'name': production.name,
                'mes_order_id': mes_order.id if mes_order else False,
                'mes_order_no': mes_order.name if mes_order else False,
                'product_id': production.product_id.id,
                'product_name': production.product_id.display_name,
                'workshop_id': production.x_workshop_id.id if production.x_workshop_id else False,
                # The production line moved to the MES orders (制令单); the MO
                # no longer carries it. Kept in the payload for API stability.
                'production_line_id': False,
                'online_state': production.x_online_state,
                'state': production.state,
            },
            'workorder': {
                'id': workorder.id,
                'name': workorder.name,
                'state': workorder.state,
                'workcenter_id': workorder.x_mes_workcenter_id.id if workorder and workorder.x_mes_workcenter_id else False,
                'workcenter_code': workorder.x_mes_workcenter_id.code if workorder and workorder.x_mes_workcenter_id else False,
                'operation_type': workorder.x_meter_operation_type if workorder else False,
            } if workorder else False,
        })

    @api.model
    def _find_scan_workcenter(self, station_code: str, company=False):
        domain = [
            '|',
            ('code', '=', station_code),
            ('name', '=', station_code),
        ]
        if company:
            domain += ['|', ('company_id', '=', False), ('company_id', '=', company.id)]
        return self.env['mrp.workcenter'].sudo().with_context(active_test=False).search(domain, limit=1)

    @api.model
    def _find_scan_production(self, mes_order_no: str | None, workcenter=None):
        if not mes_order_no:
            return self.env['mrp.production']._get_current_online_production(workcenter=workcenter)
        mes_order = self._find_mes_order(mes_order_no)
        if not mes_order:
            return self.env['mrp.production']
        production = mes_order.production_id
        if production.state in ('done', 'cancelled', 'cancel'):
            return self.env['mrp.production']
        candidates = production.workorder_ids.filtered(
            lambda workorder: workorder.state in ('ready', 'progress')
        )
        if workcenter:
            candidates = candidates.filtered(
                lambda workorder: workcenter in (
                    workorder.x_mes_workcenter_id | workorder.workcenter_id
                )
            )
        if not candidates:
            return self.env['mrp.production']
        return production.with_context(mes_order_id=mes_order.id)

    @api.model
    def _resolve_scan_workorder(self, payload: dict):
        company, company_error = self._scan_company_from_payload(payload)
        if company_error:
            return self.env['mrp.workorder']
        station_code = self._scan_payload_value(payload, 'M_WORK_STATIONSN')
        workcenter = self._find_scan_workcenter(station_code, company=company) if station_code else self.env['mrp.workcenter']
        if not workcenter:
            return self.env['mrp.workorder']
        mes_order_no = self._scan_payload_value(payload, 'M_MO_NUMBER')
        serial_number = self._scan_payload_value(payload, 'M_SN')
        production = self._find_scan_production(mes_order_no, workcenter=workcenter) if mes_order_no else self.env['mrp.production']
        if mes_order_no and not production:
            return self.env['mrp.workorder']
        if production:
            workorder = production._get_current_online_workorder(workcenter=workcenter)
            if workorder:
                return workorder
        fallback_domain = [
            ('state', 'in', ['ready', 'progress']),
            '|',
            ('x_mes_workcenter_id', '=', workcenter.id),
            ('workcenter_id', '=', workcenter.id),
        ]
        if production:
            fallback_domain.append(('production_id', '=', production.id))
        elif serial_number:
            stage_serials = self.env['sn.wsd.internal.serial'].sudo().with_context(active_test=False).search([
                ('serial_no', '=', serial_number),
                ('company_id', '=', company.id),
                ('active', '=', True),
                ('production_id.state', 'not in', ['done', 'cancel']),
            ])
            stage_serials = stage_serials.filtered(lambda serial: not serial.is_confirmed_scrapped())
            production_ids = stage_serials.mapped('production_id').ids
            if not production_ids:
                return self.env['mrp.workorder']
            fallback_domain.append(('production_id', 'in', production_ids))
        workorders = self.env['mrp.workorder'].sudo().search(
            fallback_domain,
            order='date_start asc, sequence asc, id asc',
        )
        if len(workorders) == 1:
            return workorders
        if len(workorders) > 1:
            current_links = workorders.filtered(
                lambda candidate: candidate.id in stage_serials.mapped('current_workorder_id').ids
            ) if serial_number and not production else self.env['mrp.workorder']
            if len(current_links) == 1:
                return current_links
            return self.env['mrp.workorder']
        return self.env['mrp.workorder']

    @api.model
    def _normalize_scan_test_result(self, test_result: str | None) -> str | None:
        value = (test_result or '').strip().upper()
        if value == 'OK':
            return 'pass'
        if value == 'NG':
            return 'fail'
        return None

    @api.model
    def _scan_test_detail_note(self, payload: dict | None):
        test_detail = self._scan_payload_value(payload, 'M_TEST_DETAIL')
        if isinstance(test_detail, (list, dict)):
            return json.dumps(test_detail, ensure_ascii=False, separators=(',', ':'))
        return test_detail

    @api.model
    def _scan_company_domain_from_payload(self, payload: dict | None):
        company, error = self._scan_company_from_payload(payload)
        if company and not error:
            return [('company_id', '=', company.id)]
        return [('company_id', 'in', self.env.companies.ids)]

    @api.model
    def _scan_identifier_has_active_serial(self, identifier: str, payload: dict | None = None):
        if not identifier:
            return False
        domain = [
            ('serial_no', '=', identifier),
            ('active', '=', True),
            ('production_id.state', 'not in', ['done', 'cancel']),
        ] + self._scan_company_domain_from_payload(payload)
        serials = self.env['sn.wsd.internal.serial'].sudo().with_context(active_test=False).search(domain)
        serials = serials.filtered(lambda serial: not serial.is_confirmed_scrapped())
        return bool(serials)

    @api.model
    def _find_scan_nameplate_binding(self, nameplate_code: str, payload: dict | None = None):
        if not nameplate_code:
            return self.env['sn.wsd.mes.nameplate.binding'], False
        domain = [
            ('nameplate_code', '=', nameplate_code),
            ('active', '=', True),
        ] + self._scan_company_domain_from_payload(payload)
        bindings = self.env['sn.wsd.mes.nameplate.binding'].sudo().search(
            domain,
            order='binding_time desc, id desc',
        )
        if not bindings:
            return bindings, False
        serials = bindings.mapped('internal_serial_id')
        active_serials = serials.filtered(lambda serial: serial.active and not serial.is_confirmed_scrapped())
        if not active_serials:
            return bindings[:1], self._aoi_error(
                'Nameplate code is bound to an inactive or scrapped serial number.',
                error_code='nameplate_serial_unavailable',
                nameplate_code=nameplate_code,
            )
        if len(active_serials) > 1:
            return bindings, self._aoi_error(
                'Nameplate code matches more than one active serial number.',
                error_code='nameplate_binding_ambiguous',
                nameplate_code=nameplate_code,
                internal_serial_ids=active_serials.ids,
            )
        return bindings.filtered(lambda binding: binding.internal_serial_id == active_serials[:1])[:1], False

    @api.model
    def _resolve_scan_serial_identifier(self, payload: dict):
        raw_identifier = self._scan_payload_value(payload, 'M_SN')
        nameplate_identifier = self._scan_payload_value(payload, 'M_STR1')
        context = {
            'input_code': raw_identifier,
            'input_identifier_type': 'serial',
            'resolved_serial_number': raw_identifier,
            'nameplate_code': False,
            'nameplate_binding_id': False,
        }
        if not raw_identifier and not nameplate_identifier:
            return payload, context, False
        if self._scan_identifier_has_active_serial(raw_identifier, payload):
            if nameplate_identifier:
                binding, error = self._find_scan_nameplate_binding(nameplate_identifier, payload)
                if error:
                    return payload, context, error
                if binding and binding.internal_serial_id.serial_no != raw_identifier:
                    binding_mode = self.env['sn.wsd.mes.nameplate.binding']._get_binding_mode(
                        binding.company_id
                    )
                    if binding_mode == 'strict':
                        return payload, context, self._aoi_error(
                            'Nameplate code is bound to a different serial number.',
                            error_code='nameplate_serial_mismatch',
                            serial_number=raw_identifier,
                            nameplate_code=nameplate_identifier,
                            bound_serial_number=binding.internal_serial_id.serial_no,
                            nameplate_binding_id=binding.id,
                        )
                    context['nameplate_code'] = binding.nameplate_code
                    return payload, context, False
                if binding:
                    context.update({
                        'nameplate_code': binding.nameplate_code,
                        'nameplate_binding_id': binding.id,
                    })
            return payload, context, False

        lookup_code = raw_identifier or nameplate_identifier
        binding, error = self._find_scan_nameplate_binding(lookup_code, payload)
        if error:
            return payload, context, error
        if not binding:
            if not raw_identifier and nameplate_identifier:
                return payload, context, self._aoi_error(
                    'Nameplate code is not bound to a serial number.',
                    error_code='nameplate_not_bound',
                    nameplate_code=nameplate_identifier,
                )
            return payload, context, False

        serial = binding.internal_serial_id
        resolved_payload = dict(payload or {})
        resolved_payload['M_SN'] = serial.serial_no
        if not self._scan_payload_value(resolved_payload, 'M_STR1'):
            resolved_payload['M_STR1'] = binding.nameplate_code
        context.update({
            'input_code': lookup_code,
            'input_identifier_type': 'nameplate',
            'resolved_serial_number': serial.serial_no,
            'nameplate_code': binding.nameplate_code,
            'nameplate_binding_id': binding.id,
        })
        return resolved_payload, context, False

    @api.model
    def _find_internal_serial_for_workorder(self, serial_number: str, workorder):
        if not serial_number or not workorder:
            return self.env['sn.wsd.internal.serial']
        return self.env['sn.wsd.internal.serial'].sudo().find_for_workorder_context(serial_number, workorder)

    @api.model
    def _workorder_allows_serial_creation(self, workorder):
        operation = workorder.operation_id or workorder._find_route_operation()
        return bool(
            operation
            and operation.x_allow_entry
            and operation.x_allow_serial_creation
        )

    @api.model
    def _prepare_scan_serial(self, serial_number, workorder, payload):
        serial = self._find_internal_serial_for_workorder(serial_number, workorder)
        if serial:
            return serial, False, False
        has_explicit_mes_order = bool(self._get_first_payload_value(payload, 'M_MO_NUMBER'))
        if not has_explicit_mes_order:
            return serial, False, self._aoi_error(
                'Serial stage was not found. MES order number is required at an entry operation.',
                error_code='serial_stage_not_found',
                serial_number=serial_number,
            )
        if not self._workorder_allows_serial_creation(workorder):
            return serial, False, self._aoi_error(
                'This operation does not allow serial stage creation.',
                error_code='serial_stage_creation_not_allowed',
                serial_number=serial_number,
                workorder_id=workorder.id,
            )
        try:
            serial, created = workorder.production_id.get_or_create_stage_serial(
                serial_number,
                workorder=workorder,
                allow_create=True,
                origin_type='external',
            )
        except ValidationError as error:
            return serial, False, self._aoi_error(
                str(error),
                error_code='serial_capacity_exceeded' if 'capacity' in str(error).lower() else 'serial_stage_create_failed',
                serial_number=serial_number,
                workorder_id=workorder.id,
            )
        return serial, created, False

    @api.model
    def _validate_serial_for_workorder(self, serial_number: str, workorder):
        serial = self._find_internal_serial_for_workorder(serial_number, workorder)
        if not serial:
            return serial, self._aoi_error(
                'Serial number not found.',
                error_code='serial_not_found',
                serial_number=serial_number,
            )
        if not serial.active:
            return serial, self._aoi_error(
                'Serial number is inactive.',
                error_code='serial_inactive',
                serial_number=serial_number,
                internal_serial_id=serial.id,
            )
        if serial.product_id != workorder.product_id:
            return serial, self._aoi_error(
                'Serial number product does not match the work order product.',
                error_code='serial_product_mismatch',
                serial_number=serial_number,
                expected_product_id=workorder.product_id.id,
                actual_product_id=serial.product_id.id,
            )
        mes_order = self.env['sn.wsd.mes.order'].browse(
            workorder.env.context.get('mes_order_id')
        ).exists() if workorder.env.context.get('mes_order_id') else self.env['sn.wsd.mes.order']
        if mes_order and serial.mes_order_id and serial.mes_order_id != mes_order:
            return serial, self._aoi_error(
                'Serial number MES order does not match the work order.',
                error_code='serial_mes_order_mismatch',
                serial_number=serial_number,
                expected_mes_order_id=mes_order.id,
                actual_mes_order_id=serial.mes_order_id.id,
            )
        if (
            serial.production_id
            and serial.production_id != workorder.production_id
        ):
            return serial, self._aoi_error(
                'Serial number manufacturing order does not match the work order.',
                error_code='serial_production_mismatch',
                serial_number=serial_number,
                expected_production_id=workorder.production_id.id,
                actual_production_id=serial.production_id.id,
            )
        if (
            serial.current_production_id
            and serial.current_production_id != workorder.production_id
        ):
            return serial, self._aoi_error(
                'Serial number current manufacturing order does not match the work order.',
                error_code='serial_current_production_mismatch',
                serial_number=serial_number,
                expected_production_id=workorder.production_id.id,
                actual_production_id=serial.current_production_id.id,
            )
        if serial.final_result == 'scrap':
            return serial, self._aoi_error(
                'Serial number has been scrapped.',
                error_code='serial_scrapped',
                serial_number=serial_number,
                internal_serial_id=serial.id,
            )
        if serial.pack_date:
            return serial, self._aoi_error(
                'Serial number has already been packed.',
                error_code='serial_already_packed',
                serial_number=serial_number,
                internal_serial_id=serial.id,
            )
        return serial, False

    @api.model
    def _get_scan_operation_retry_limit(self, workorder):
        if not workorder:
            return 0
        operation = workorder.operation_id or workorder._find_route_operation()
        return max(int(operation.x_ng_retry_limit or 0), 0) if operation and 'x_ng_retry_limit' in operation._fields else 0

    @api.model
    def _prepare_scan_retry_context(self, serial, workorder, result):
        retry_limit = self._get_scan_operation_retry_limit(workorder)
        retry_sequence = 0
        requires_repair = False
        if serial and workorder and result == 'fail':
            existing_fail_count = self.env['sn.wsd.mes.test.result'].search_count([
                ('internal_serial_id', '=', serial.id),
                ('workorder_id', '=', workorder.id),
                ('result', '=', 'fail'),
            ])
            retry_sequence = existing_fail_count + 1
            requires_repair = bool(retry_limit and retry_sequence >= retry_limit)
        return {
            'retry_sequence': retry_sequence,
            'retry_limit': retry_limit,
            'requires_repair': requires_repair,
        }

    @api.model
    def _prepare_scan_rework_context(self, serial, workorder, result):
        is_rework_pass = bool(serial and workorder and result == 'pass' and serial._workorder_in_current_rework_window(workorder))
        return {
            'is_rework_pass': is_rework_pass,
            'rework_source_workorder_id': serial.x_rework_source_workorder_id.id if is_rework_pass else False,
        }

    @api.model
    def _find_scan_repair_workorder(self, serial, source_workorder):
        if not serial or not source_workorder:
            return self.env['mrp.workorder']
        productions = source_workorder.production_id
        workorders = productions.mapped('workorder_ids').filtered(
            lambda workorder: (
                workorder.state not in ('done', 'cancel')
                and (
                    workorder.operation_id.x_route_operation_id.x_station_type == 'repair'
                    or workorder.x_meter_operation_type in ('pcb_repair',)
                )
            )
        )
        if not workorders:
            return self.env['mrp.workorder']
        after_source = workorders.filtered(lambda workorder: workorder.production_id == source_workorder.production_id and (workorder.sequence, workorder.id) >= (source_workorder.sequence, source_workorder.id))
        return (after_source or workorders).sorted(lambda workorder: (workorder.production_id.id, workorder.sequence, workorder.id))[:1]

    @api.model
    def _apply_scan_repair_requirement(self, serial, source_workorder, operator_code=None, note=None):
        repair_workorder = self._find_scan_repair_workorder(serial, source_workorder)
        target_workorder = repair_workorder or source_workorder
        already_required = (
            serial.x_mes_repair_state == 'repair_required'
            and serial.x_rework_source_workorder_id == source_workorder
        )
        serial.write({
            'x_mes_repair_state': 'repair_required',
            'x_rework_source_workorder_id': source_workorder.id,
            'x_rework_exit_workorder_id': source_workorder.id,
            'current_workorder_id': target_workorder.id,
            'current_operation_id': target_workorder.operation_id.id,
            'current_workcenter_id': target_workorder.workcenter_id.id,
        })
        if repair_workorder and not already_required:
            self.env['sn.wsd.mes.sn.travel'].record_event(
                serial_number=serial.serial_no,
                event_type='repair',
                workcenter_code=repair_workorder.x_mes_workcenter_id.code or repair_workorder.workcenter_id.code,
                workorder_id=repair_workorder.id,
                production_id=repair_workorder.production_id.id,
                result='hold',
                operator_code=operator_code,
                note=note or 'NG retry limit reached; routed to repair.',
                source_system='SCAN_PASS',
                internal_serial_id=serial.id,
            )
        return repair_workorder

    @api.model
    def _scan_result_context_from_record(self, data, retry_context, rework_context):
        test_result = self.env['sn.wsd.mes.test.result'].browse(data.get('test_result_id')).exists() if data.get('test_result_id') else self.env['sn.wsd.mes.test.result']
        if test_result:
            retry_context = {
                'retry_sequence': test_result.retry_sequence,
                'retry_limit': test_result.retry_limit,
                'requires_repair': test_result.requires_repair,
            }
            rework_context = {
                'is_rework_pass': test_result.is_rework_pass,
                'rework_source_workorder_id': test_result.rework_source_workorder_id.id,
            }
        return retry_context, rework_context, test_result

    @api.model
    def submit_scan_pass(
        self,
        payload: dict,
        source_system: str | None = 'SCAN_PASS',
        override_route: bool = False,
    ) -> dict:
        if not isinstance(payload, dict):
            return self._aoi_error('Payload must be a JSON object.')
        company, context_error = self._validate_scan_required_context(payload)
        if context_error:
            return context_error
        serial_number = self._scan_payload_value(payload, 'M_SN')
        station_code = self._scan_payload_value(payload, 'M_WORK_STATIONSN')
        operator_code = self._scan_payload_value(payload, 'M_EMP')
        raw_result = self._scan_payload_value(payload, 'M_TEST_RESULT')
        normalized_result = self._normalize_scan_test_result(raw_result)
        if not serial_number:
            return self._aoi_error('Missing required field: M_SN')
        if not station_code:
            return self._aoi_error('Missing required field: M_WORK_STATIONSN')
        if not normalized_result:
            return self._aoi_error('Test result must be OK or NG.', M_TEST_RESULT=raw_result)
        workcenter = self._find_scan_workcenter(station_code, company=company)
        if not workcenter:
            return self._aoi_error('Work center not found.', M_WORK_STATIONSN=station_code)
        workorder = self._resolve_scan_workorder(payload)
        if not workorder:
            return self._aoi_error(
                'Active work order not found for the MES order and work center.',
                M_MO_NUMBER=self._get_first_payload_value(payload, 'M_MO_NUMBER'),
                M_WORK_STATIONSN=station_code,
            )

        serial, serial_created, serial_prepare_error = self._prepare_scan_serial(serial_number, workorder, payload)
        if serial_prepare_error:
            return serial_prepare_error
        serial, serial_error = self._validate_serial_for_workorder(serial_number, workorder)
        if serial_error:
            return serial_error

        mes_order = self._find_mes_order(
            self._scan_payload_value(payload, 'M_MO_NUMBER')
        )
        external_event_id = self._resolve_scan_external_event_id(payload)
        note = self._scan_test_detail_note(payload)
        metadata_payload = self._prepare_payload_metadata(
            payload=payload,
            external_event_id=external_event_id,
            source_system=source_system,
        )
        retry_context = self._prepare_scan_retry_context(serial, workorder, normalized_result)
        rework_context = self._prepare_scan_rework_context(serial, workorder, normalized_result)
        if normalized_result == 'pass':
            result = self.submit_workorder_event(
                workorder_id=workorder.id,
                event_type='complete',
                serial_number=serial_number,
                operator_code=operator_code,
                note=note,
                override_route=override_route,
                external_event_id=external_event_id,
                source_system=source_system,
                payload=metadata_payload,
            )
        else:
            result = self.submit_test_result(
                workorder_id=workorder.id,
                serial_number=serial_number,
                result='fail',
                operator_code=operator_code,
                note=note,
                payload=metadata_payload,
                external_event_id=external_event_id,
                source_system=source_system,
                retry_sequence=retry_context['retry_sequence'],
                retry_limit=retry_context['retry_limit'],
                requires_repair=retry_context['requires_repair'],
            )
        if result.get('ok'):
            data = dict(result.get('data') or {})
            retry_context, rework_context, test_result = self._scan_result_context_from_record(
                data, retry_context, rework_context,
            )
            if normalized_result == 'fail' and retry_context['requires_repair']:
                repair_workorder = self._apply_scan_repair_requirement(
                    serial,
                    workorder,
                    operator_code=operator_code,
                    note=note,
                )
                if repair_workorder:
                    data['repair_workorder_id'] = repair_workorder.id
            data.update({
                'serial_number': serial_number,
                'workorder_id': workorder.id,
                'production_id': workorder.production_id.id,
                'mes_order_id': mes_order.id if mes_order else False,
                'workcenter_id': workcenter.id,
                'workcenter_code': workcenter.code,
                'result': normalized_result,
                'source_system': source_system,
                'internal_serial_id': serial.id,
                'serial_stage_created': serial_created,
                'retry_sequence': retry_context['retry_sequence'],
                'retry_limit': retry_context['retry_limit'],
                'requires_repair': retry_context['requires_repair'],
                'is_rework_pass': rework_context['is_rework_pass'],
                'rework_source_workorder_id': rework_context['rework_source_workorder_id'],
            })
            return self._aoi_response(data=data)
        error = result.get('error') or {}
        return self._aoi_error(error.get('message') or 'Scan pass failed.', **(error.get('details') or {}))

    @api.model
    def submit_workorder_event(
        self,
        workorder_id: int,
        event_type: str,
        serial_number: str | None = None,
        operator_code: str | None = None,
        note: str | None = None,
        override_route: bool = False,
        external_event_id: str | None = None,
        source_system: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        """
        Submit a start or complete event for one manufacturing work order.

        The method wraps the MES execution actions exposed by the work
        order model and returns a stable JSON-friendly response for
        external devices.

        :param workorder_id: Manufacturing work order ID.
        :param event_type: Supported values are ``start`` and ``complete``.
        :param serial_number: Finished product serial number when the station works in serial mode.
        :param operator_code: Operator login or external operator code.
        :param note: Optional execution note or terminal remark.
        :param override_route: Whether route blocking rules may be bypassed when allowed by configuration.
        :param external_event_id: External idempotency key for the device event.
        :param source_system: External source system name.
        :returns: A standard API payload produced by the MES execution flow.
        :raises ValueError: If ``event_type`` is not supported.
        """
        workorder = self.env['mrp.workorder'].browse(workorder_id).exists()
        if not workorder:
            return self._service_error(
                'workorder_not_found',
                'Work order not found.',
                workorder_id=workorder_id,
            )
        if event_type == 'start':
            result = workorder.action_mes_start(
                serial_number=serial_number,
                operator_code=operator_code,
                note=note,
                override_route=override_route,
                external_event_id=external_event_id,
                request_id=False,
                source_system=source_system,
            )
            if result.get('ok') and hasattr(workorder, 'action_register_terminal_report'):
                report = workorder.action_register_terminal_report(
                    source_type='api',
                    report_type='start',
                    operator_code=operator_code,
                    device=workorder.x_meter_equipment_id,
                    external_event_id=external_event_id,
                    event_time=False,
                    qty_in=1.0 if serial_number else 0.0,
                    qty_ok=0.0,
                    qty_ng=0.0,
                    qty_scrap=0.0,
                    qty_repair=0.0,
                    qty_rework=0.0,
                    serial_no=serial_number,
                    remark=note,
                    payload_json=json.dumps(
                        self._prepare_payload_metadata(
                            payload=payload,
                            external_event_id=external_event_id,
                            source_system=source_system,
                        ),
                        ensure_ascii=True,
                    ),
                )
            return self._normalize_mes_result(result)
        if event_type == 'complete':
            result = workorder.action_mes_complete(
                serial_number=serial_number,
                operator_code=operator_code,
                note=note,
                override_route=override_route,
                external_event_id=external_event_id,
                request_id=False,
                source_system=source_system,
            )
            if result.get('ok') and hasattr(workorder, 'action_register_terminal_report'):
                report = workorder.action_register_terminal_report(
                    source_type='api',
                    report_type='complete',
                    operator_code=operator_code,
                    device=workorder.x_meter_equipment_id,
                    external_event_id=external_event_id,
                    event_time=False,
                    qty_in=1.0 if serial_number else 0.0,
                    qty_ok=1.0 if serial_number else 0.0,
                    qty_ng=0.0,
                    qty_scrap=0.0,
                    qty_repair=0.0,
                    qty_rework=0.0,
                    serial_no=serial_number,
                    remark=note,
                    payload_json=json.dumps(
                        self._prepare_payload_metadata(
                            payload=payload,
                            external_event_id=external_event_id,
                            source_system=source_system,
                        ),
                        ensure_ascii=True,
                    ),
                )
            return self._normalize_mes_result(result)
        raise ValueError(f'Unsupported event_type: {event_type}')

    @api.model
    def submit_test_result(
        self,
        workorder_id: int,
        serial_number: str,
        result: str = 'pass',
        operator_code: str | None = None,
        cycle_time_sec: float | None = None,
        basic_error: float | None = None,
        phase_error: float | None = None,
        aging_temp_c: float | None = None,
        tester_channel: str | None = None,
        note: str | None = None,
        payload: dict | None = None,
        external_event_id: str | None = None,
        source_system: str | None = None,
        retry_sequence: int = 0,
        retry_limit: int = 0,
        requires_repair: bool = False,
        is_rework_pass: bool = False,
        rework_source_workorder_id: int | None = None,
    ) -> dict:
        """
        Submit one MES test result to the current manufacturing flow.

        This method is the preferred JSON-2 entry for test benches or
        machine gateways. It delegates to the work order MES test flow
        and preserves the raw payload for traceability.

        :param workorder_id: Manufacturing work order ID.
        :param serial_number: Finished product serial number.
        :param result: Test result, one of ``pass``, ``fail``, or ``hold``.
        :param operator_code: Operator login or external operator code.
        :param cycle_time_sec: Test cycle time in seconds.
        :param basic_error: Basic error value reported by the device.
        :param phase_error: Phase error value reported by the device.
        :param aging_temp_c: Aging temperature in Celsius when relevant.
        :param tester_channel: Device-side test channel identifier.
        :param note: Optional test note.
        :param payload: Raw device payload preserved for traceability.
        :param external_event_id: External idempotency key for the device event.
        :param source_system: External source system name.
        :returns: A standard API payload with created test result and travel IDs.
        """
        workorder = self.env['mrp.workorder'].browse(workorder_id).exists()
        if not workorder:
            return self._service_error(
                'workorder_not_found',
                'Work order not found.',
                workorder_id=workorder_id,
            )
        serial = self.env['sn.wsd.internal.serial'].find_for_workorder_context(serial_number, workorder)
        if serial and result == 'pass' and not is_rework_pass:
            rework_context = self._prepare_scan_rework_context(serial, workorder, result)
            is_rework_pass = rework_context['is_rework_pass']
            rework_source_workorder_id = rework_context['rework_source_workorder_id']
        result = workorder.action_mes_log_test(
            serial_number=serial_number,
            result=result,
            operator_code=operator_code,
            cycle_time_sec=cycle_time_sec,
            basic_error=basic_error,
            phase_error=phase_error,
            aging_temp_c=aging_temp_c,
            tester_channel=tester_channel,
            note=note,
            payload=self._prepare_payload_metadata(
                payload=payload,
                external_event_id=external_event_id,
                source_system=source_system,
            ),
            external_event_id=external_event_id,
            request_id=False,
            source_system=source_system,
            retry_sequence=retry_sequence,
            retry_limit=retry_limit,
            requires_repair=requires_repair,
            is_rework_pass=is_rework_pass,
            rework_source_workorder_id=rework_source_workorder_id,
        )
        if result.get('ok') and serial and is_rework_pass:
            serial._mark_rework_step_passed(workorder)
        return self._normalize_mes_result(result)

    @api.model
    def upload_finished_serials(
        self,
        mes_order_id: int | None,
        serials: list[dict] | list[str],
        source_system: str | None = None,
    ) -> dict:
        """
        Upload finished serial numbers for one SMT manufacturing order.

        The target manufacturing order must be an SMT process order.
        Each item may either be a plain serial string or a mapping with
        keys such as ``serial_no`` and ``panel_no``.

        :param mes_order_id: MES order ID.
        :param serials: Serial list to upload. Example:
            ``[{'panel_no': 'PANEL001', 'serial_no': 'SN001'}]``.
        :param source_system: External source system name.
        :returns: Upload result containing manufacturing, lot, and archive IDs.
        """
        mes_order = self.env['sn.wsd.mes.order'].browse(mes_order_id).exists() if mes_order_id else self.env['sn.wsd.mes.order']
        production = self._select_mes_order_production(mes_order, smt_required=True) if mes_order else self.env['mrp.production']
        if not production:
            return self._service_error(
                'production_not_found',
                'SMT manufacturing order was not found for the MES order.',
                mes_order_id=mes_order_id or False,
            )
        result = production.api_upload_finished_serials(serials)
        data = dict(result)
        data.update({
            'mes_order_id': mes_order.id if mes_order else False,
            'mes_order_no': mes_order.name if mes_order else False,
        })
        if source_system:
            data['source_system'] = source_system
        return self._service_ok(data)

    @api.model
    def get_serial_trace(
        self,
        serial_number: str,
        include_test_results: bool = True,
        travel_limit: int = 50,
        test_result_limit: int = 50,
    ) -> dict:
        """
        Get travel and test traceability data for one internal serial number.

        :param serial_number: Internal serial number.
        :param include_test_results: Whether MES test results should be included.
        :param travel_limit: Maximum number of travel events to return.
        :param test_result_limit: Maximum number of test results to return.
        :returns: Serial traceability payload with latest state, travel history, and test history.
        """
        archives = self.env['sn.wsd.internal.serial'].with_context(active_test=False).search([
            ('serial_no', '=', serial_number),
            ('company_id', 'in', self.env.companies.ids),
        ], order='production_date, id')
        if not archives:
            return self._service_error(
                'serial_not_found',
                'Serial number not found.',
                serial_number=serial_number,
            )
        travel_records = self.env['sn.wsd.mes.sn.travel'].search(
            [('internal_serial_id', 'in', archives.ids)],
            order='event_time desc, id desc',
            limit=travel_limit,
        )
        test_records = self.env['sn.wsd.mes.test.result']
        if include_test_results:
            test_records = test_records.search(
                [('internal_serial_id', 'in', archives.ids)],
                order='test_time desc, id desc',
                limit=test_result_limit,
            )
        latest_event = travel_records[:1]
        return self._service_ok({
            'serial_number': serial_number,
            'identity_id': archives.serial_identity_id[:1].id,
            'internal_serial_id': archives[-1:].id,
            'stages': [
                {
                    'internal_serial_id': archive.id,
                    'product_id': archive.product_id.id,
                    'product_name': archive.product_id.display_name,
                    'production_id': archive.production_id.id,
                    'mes_order_id': archive.mes_order_id.id,
                    'state': archive.final_result or 'pending',
                    'final_result': archive.final_result,
                    'active': archive.active,
                    'source_internal_serial_id': archive.parent_id.id,
                    'source_lot_id': archive.source_lot_id.id,
                    'lot_id': archive.lot_id.id,
                }
                for archive in archives
            ],
            'archive': {
                'id': archives[-1].id,
                'state': archives[-1].final_result or 'pending',
                'final_result': archives[-1].final_result,
                'production_id': archives[-1].production_id.id if archives[-1].production_id else False,
                'current_workorder_id': archives[-1].current_workorder_id.id if archives[-1].current_workorder_id else False,
                'panel_no': archives[-1].x_panel_no,
            },
            'latest_event': {
                'id': latest_event.id,
                'event_time': latest_event.event_time,
                'workcenter_code': latest_event.workcenter_code,
                'event_type': latest_event.event_type,
                'result': latest_event.result,
                'external_event_id': latest_event.external_event_id,
                'source_system': latest_event.source_system,
            } if latest_event else False,
            'travel_history': [
                {
                    'id': record.id,
                    'event_time': record.event_time,
                    'workcenter_code': record.workcenter_code,
                    'event_type': record.event_type,
                    'result': record.result,
                    'operator_code': record.operator_code,
                    'external_event_id': record.external_event_id,
                    'source_system': record.source_system,
                    'note': record.note,
                }
                for record in travel_records
            ],
            'test_results': [
                {
                    'id': record.id,
                    'test_time': record.test_time,
                    'test_type': record.test_type,
                    'result': record.result,
                    'workcenter_code': record.workcenter_code,
                    'cycle_time_sec': record.cycle_time_sec,
                    'external_event_id': record.external_event_id,
                    'source_system': record.source_system,
                    'note': record.note,
                }
                for record in test_records
            ] if include_test_results else [],
        })

    @api.model
    def _resolve_smt_loading_context(self, payload):
        production_id = self._get_first_payload_value(
            payload, 'production_id', 'productionId', 'manufacturing_order_id', 'manufacturingOrderId',
        )
        production = self.env['mrp.production']
        if production_id:
            try:
                production = self.env['mrp.production'].browse(int(production_id)).exists()
            except (TypeError, ValueError):
                raise ValidationError('Manufacturing order ID is invalid.')
        if not production:
            mo_number = self._get_first_payload_value(payload, 'mo_number', 'moNumber', 'manufacturing_order')
            production = self.env['mrp.production'].search([('name', '=', mo_number)], limit=1) if mo_number else production
        workcenter_id = self._get_first_payload_value(payload, 'workcenter_id', 'workcenterId')
        try:
            workcenter = self.env['mrp.workcenter'].browse(int(workcenter_id)).exists() if workcenter_id else self.env['mrp.workcenter']
        except (TypeError, ValueError):
            raise ValidationError('Work center ID is invalid.')
        if not production:
            raise ValidationError('Manufacturing order was not found.')
        if not workcenter:
            raise ValidationError('Work center was not found.')
        required = {
            'device_table': self._get_first_payload_value(payload, 'device_table', 'deviceTable'),
            'loadpoint': self._get_first_payload_value(payload, 'loadpoint', 'loadPoint'),
            'feeder_sn': self._get_first_payload_value(payload, 'feeder_sn', 'feederSn'),
            'material_sn': self._get_first_payload_value(payload, 'material_sn', 'materialSn'),
        }
        missing = [key for key, value in required.items() if value in (None, '')]
        if missing:
            raise ValidationError('Missing SMT loading fields: %s' % ', '.join(missing))
        return production, workcenter, required

    @api.model
    def smt_loading_validate(self, payload):
        production, workcenter, values = self._resolve_smt_loading_context(payload or {})
        result = self.env['sn.smt.loading.service'].validate_loading(production, workcenter, **values)
        return self._service_ok(result)

    @api.model
    def smt_loading_save(self, payload):
        production, workcenter, values = self._resolve_smt_loading_context(payload or {})
        result = self.env['sn.smt.loading.service'].save_loading(production, workcenter, **values)
        return self._service_ok(result)
