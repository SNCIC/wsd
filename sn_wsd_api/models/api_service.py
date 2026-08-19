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
        if not result:
            return self._service_ok({})
        if result.get('code') and result.get('code') != 200:
            return self._service_error(
                result.get('data', {}).get('error_code', 'mes_operation_error'),
                result.get('message') or 'MES operation failed.',
                **(result.get('data') or {}),
            )
        if result.get('code') == 200:
            return self._service_ok(result.get('data') or {})
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

        mes_order, route_operation, mes_context_error = self._resolve_scan_mes_context(payload, workcenter)
        if mes_context_error:
            return self._strict_external_error(mes_context_error.get('message') or 'MES order context not found.')

        serial, serial_error = self._validate_serial_for_mes_order(product_sn, mes_order)
        if serial_error:
            return self._strict_external_error(serial_error.get('message') or 'Serial validation failed.')

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
            production_id=mes_order.production_id.id,
            mes_order_id=mes_order.id,
            route_operation_id=route_operation.id,
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
                'route_operation': False,
            })
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
                # Online gating moved to the MES orders (制令单); kept in
                # the payload as False for API stability.
                'online_state': False,
                'state': production.state,
            },
            'route_operation': False,
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
        return production.with_context(mes_order_id=mes_order.id)

    @api.model
    def _resolve_scan_mes_context(self, payload: dict, workcenter):
        mes_order_no = self._scan_payload_value(payload, 'M_MO_NUMBER')
        if not mes_order_no:
            return False, False, self._aoi_error(
                'MES order number is required.',
                error_code='mes_order_required',
            )
        mes_order = self._find_mes_order(mes_order_no)
        if not mes_order:
            return False, False, self._aoi_error(
                'MES order not found.',
                error_code='mes_order_not_found',
                M_MO_NUMBER=mes_order_no,
            )
        if mes_order.state in ('done', 'cancelled'):
            return False, False, self._aoi_error(
                'MES order is closed.',
                error_code='mes_order_closed',
                mes_order_id=mes_order.id,
                state=mes_order.state,
            )
        try:
            route_operation = mes_order._resolve_route_operation(workcenter)
        except ValidationError as error:
            return False, False, self._aoi_error(
                str(error),
                error_code='route_operation_not_found',
                mes_order_id=mes_order.id,
                workcenter_id=workcenter.id,
            )
        return mes_order, route_operation, False

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
    def _find_internal_serial_for_mes_order(self, serial_number: str, mes_order):
        if not serial_number or not mes_order:
            return self.env['sn.wsd.internal.serial']
        return self.env['sn.wsd.internal.serial'].sudo().find_for_manufacturing_context(
            serial_number,
            company=mes_order.company_id,
            production=mes_order.production_id,
            mes_order=mes_order,
            product=mes_order.product_id,
        )

    @api.model
    def _route_operation_allows_serial_creation(self, route_operation):
        return bool(
            route_operation
            and route_operation.x_allow_entry
            and route_operation.x_allow_serial_creation
        )

    @api.model
    def _prepare_scan_serial_for_mes_operation(self, serial_number, mes_order, route_operation, payload):
        serial = self._find_internal_serial_for_mes_order(serial_number, mes_order)
        if serial:
            return serial, False, False
        if not self._route_operation_allows_serial_creation(route_operation):
            return serial, False, self._aoi_error(
                'This operation does not allow serial stage creation.',
                error_code='serial_stage_creation_not_allowed',
                serial_number=serial_number,
                mes_order_id=mes_order.id,
                route_operation_id=route_operation.id,
            )
        try:
            serial, created = mes_order.production_id.get_or_create_stage_serial(
                serial_number,
                workorder=False,
                allow_create=True,
                origin_type='external',
            )
            if serial and not serial.mes_order_id:
                serial.mes_order_id = mes_order.id
        except ValidationError as error:
            return serial, False, self._aoi_error(
                str(error),
                error_code='serial_capacity_exceeded' if 'capacity' in str(error).lower() else 'serial_stage_create_failed',
                serial_number=serial_number,
                mes_order_id=mes_order.id,
                route_operation_id=route_operation.id,
            )
        return serial, created, False

    @api.model
    def _validate_serial_for_mes_order(self, serial_number: str, mes_order):
        serial = self._find_internal_serial_for_mes_order(serial_number, mes_order)
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
        if serial.product_id != mes_order.product_id:
            return serial, self._aoi_error(
                'Serial number product does not match the MES order product.',
                error_code='serial_product_mismatch',
                serial_number=serial_number,
                expected_product_id=mes_order.product_id.id,
                actual_product_id=serial.product_id.id,
            )
        if serial.mes_order_id and serial.mes_order_id != mes_order:
            return serial, self._aoi_error(
                'Serial number MES order does not match the request.',
                error_code='serial_mes_order_mismatch',
                serial_number=serial_number,
                expected_mes_order_id=mes_order.id,
                actual_mes_order_id=serial.mes_order_id.id,
            )
        if serial.production_id and serial.production_id != mes_order.production_id:
            return serial, self._aoi_error(
                'Serial number manufacturing order does not match the MES order.',
                error_code='serial_production_mismatch',
                serial_number=serial_number,
                expected_production_id=mes_order.production_id.id,
                actual_production_id=serial.production_id.id,
            )
        if serial.current_production_id and serial.current_production_id != mes_order.production_id:
            return serial, self._aoi_error(
                'Serial number current manufacturing order does not match the MES order.',
                error_code='serial_current_production_mismatch',
                serial_number=serial_number,
                expected_production_id=mes_order.production_id.id,
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
    def _prepare_scan_retry_context_for_mes_operation(self, serial, route_operation, result):
        retry_limit = max(int(route_operation.x_ng_retry_limit or 0), 0) if route_operation and 'x_ng_retry_limit' in route_operation._fields else 0
        retry_sequence = 0
        requires_repair = False
        if serial and route_operation and result == 'fail':
            existing_fail_count = self.env['sn.wsd.mes.test.result'].search_count([
                ('internal_serial_id', '=', serial.id),
                ('route_operation_id', '=', route_operation.id),
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
    def _record_mes_order_scan_event(
        self,
        mes_order,
        route_operation,
        serial,
        workcenter,
        result,
        operator_code=None,
        note=None,
        payload=None,
        external_event_id=None,
        source_system=None,
        retry_context=None,
    ):
        retry_context = retry_context or {}
        serial_identity = serial.serial_identity_id
        if result == 'pass':
            if not self.env['sn.wsd.serial.wip'].search([
                ('serial_identity_id', '=', serial_identity.id),
                ('mes_order_id', '=', mes_order.id),
                ('route_operation_id', '=', route_operation.id),
            ], limit=1):
                mes_order.enter_station(serial_identity, route_operation, workcenter=workcenter)
            mes_order.leave_station(serial_identity, 'ok')
            travel_result = 'pass'
            event_type = 'complete'
        else:
            travel_result = 'fail'
            event_type = 'fail'
        test_result = self.env['sn.wsd.mes.test.result'].ingest_meter_test_result(
            serial_number=serial.serial_no,
            test_type=route_operation.x_station_type if route_operation.x_station_type in ('programming', 'inspection', 'aging', 'calibration', 'final_test', 'packaging') else 'final_test',
            result=result,
            workcenter_code=workcenter.code,
            production_id=mes_order.production_id.id,
            operator_code=operator_code,
            note=note,
            payload=payload,
            external_event_id=False,
            source_system=source_system,
            retry_sequence=retry_context.get('retry_sequence', 0),
            retry_limit=retry_context.get('retry_limit', 0),
            requires_repair=retry_context.get('requires_repair', False),
            mes_order_id=mes_order.id,
            route_operation_id=route_operation.id,
            travel_event_type=event_type,
            travel_result=travel_result,
        )
        if isinstance(test_result, dict) and test_result.get('error'):
            return test_result
        return self._service_ok({
            'travel_id': test_result.get('travel_id') if isinstance(test_result, dict) else False,
            'test_result_id': test_result.get('test_result_id') if isinstance(test_result, dict) else False,
            'mes_order_id': mes_order.id,
            'route_operation_id': route_operation.id,
            'workcenter_id': workcenter.id,
            'workcenter_code': workcenter.code,
            'serial_number': serial.serial_no,
            'result': result,
        })

    @api.model
    def _scan_result_context_from_record(self, data, retry_context, rework_context):
        test_result = self.env['sn.wsd.mes.test.result'].browse(data.get('test_result_id')).exists() if data.get('test_result_id') else self.env['sn.wsd.mes.test.result']
        if test_result:
            retry_context = {
                'retry_sequence': test_result.retry_sequence,
                'retry_limit': test_result.retry_limit,
                'requires_repair': test_result.requires_repair,
            }
            rework_context = {'is_rework_pass': test_result.is_rework_pass}
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
        mes_order, route_operation, mes_context_error = self._resolve_scan_mes_context(payload, workcenter)
        if mes_context_error:
            return mes_context_error
        serial, serial_created, serial_prepare_error = self._prepare_scan_serial_for_mes_operation(
            serial_number, mes_order, route_operation, payload,
        )
        if serial_prepare_error:
            return serial_prepare_error
        serial, serial_error = self._validate_serial_for_mes_order(serial_number, mes_order)
        if serial_error:
            return serial_error

        external_event_id = self._resolve_scan_external_event_id(payload)
        note = self._scan_test_detail_note(payload)
        metadata_payload = self._prepare_payload_metadata(
            payload=payload,
            external_event_id=external_event_id,
            source_system=source_system,
        )
        retry_context = self._prepare_scan_retry_context_for_mes_operation(
            serial, route_operation, normalized_result,
        )
        result = self._record_mes_order_scan_event(
            mes_order,
            route_operation,
            serial,
            workcenter,
            normalized_result,
            operator_code=operator_code,
            note=note,
            payload=metadata_payload,
            external_event_id=external_event_id,
            source_system=source_system,
            retry_context=retry_context,
        )
        if result.get('ok'):
            data = dict(result.get('data') or {})
            data.update({
                'serial_number': serial_number,
                'production_id': mes_order.production_id.id,
                'mes_order_id': mes_order.id,
                'route_operation_id': route_operation.id,
                'workcenter_id': workcenter.id,
                'workcenter_code': workcenter.code,
                'result': normalized_result,
                'source_system': source_system,
                'internal_serial_id': serial.id,
                'serial_stage_created': serial_created,
                'retry_sequence': retry_context['retry_sequence'],
                'retry_limit': retry_context['retry_limit'],
                'requires_repair': retry_context['requires_repair'],
                'is_rework_pass': False,
            })
            return self._aoi_response(data=data)
        error = result.get('error') or {}
        return self._aoi_error(error.get('message') or 'Scan pass failed.', **(error.get('details') or {}))

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
                'current_route_operation_id': archives[-1].current_route_operation_id.id if archives[-1].current_route_operation_id else False,
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
