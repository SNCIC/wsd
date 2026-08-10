import json
import logging

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request


_logger = logging.getLogger(__name__)

MSG_QUERY_SUCCESS = '\u67e5\u8be2\u6210\u529f'
MSG_SAVE_SUCCESS = '\u4fdd\u5b58\u6210\u529f'
MSG_BAD_REQUEST = '\u8bf7\u6c42\u683c\u5f0f\u9519\u8bef'
MSG_PARAM_EMPTY = '\u53c2\u6570\u4e0d\u80fd\u4e3a\u7a7a'
MSG_SYSTEM_ERROR = '\u7cfb\u7edf\u9519\u8bef'


class SnWsdRestApiController(http.Controller):

    def _read_json_body(self):
        raw_body = request.httprequest.get_data(cache=False, as_text=True)
        if not raw_body:
            return {}
        payload = json.loads(raw_body)
        return payload if isinstance(payload, dict) else False

    def _json_response(self, payload, status=200):
        return request.make_json_response(payload, status=status)

    def _error_response(self, code=400, message=MSG_BAD_REQUEST, data=None, status=None):
        response = {
            'code': code,
            'message': message,
        }
        if data is not None:
            response['data'] = data
        response_status = status if status is not None else code if code >= 400 else 200
        return self._json_response(response, status=response_status)

    def _service(self):
        return request.env['sn.wsd.api.service'].sudo()

    def _body_or_error(self):
        try:
            body = self._read_json_body()
        except ValueError:
            return False, self._error_response(400, MSG_BAD_REQUEST, status=400)
        if body is False:
            return False, self._error_response(400, MSG_BAD_REQUEST, status=400)
        return body, False

    def _payload_from_body(self, body):
        payload = body.get('payload')
        return payload if isinstance(payload, dict) else body

    def _as_bool(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'y', 'on')
        return bool(value)

    def _as_int(self, value):
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _has_value(self, body, *field_names):
        return any(body.get(field_name) not in (None, '') for field_name in field_names)

    def _required_error(self, fields):
        return self._error_response(400, MSG_PARAM_EMPTY, data={'fields': fields}, status=400)

    def _business_error_response(self, error):
        return self._error_response(400, str(error), data={}, status=400)

    def _response_status(self, result):
        try:
            code = int(result.get('code', 200))
        except (TypeError, ValueError):
            return 200
        return code if code >= 400 else 200

    def _normalize_service_result(self, result, success_message=MSG_QUERY_SUCCESS):
        if isinstance(result, dict) and 'code' in result:
            return self._json_response(result, status=self._response_status(result))
        if isinstance(result, dict) and result.get('ok'):
            return self._json_response({
                'code': 200,
                'message': success_message,
                'data': result.get('data', {}),
            })
        if isinstance(result, dict) and result.get('ok') is False:
            error = result.get('error')
            if isinstance(error, dict):
                return self._error_response(
                    code=400,
                    message=error.get('message') or error.get('code') or MSG_SYSTEM_ERROR,
                    data=error.get('details') or {},
                    status=400,
                )
            return self._error_response(
                code=400,
                message=result.get('message') or error or MSG_SYSTEM_ERROR,
                status=400,
            )
        return self._json_response({
            'code': 200,
            'message': success_message,
            'data': result,
        })

    def _handle_payload_service(self, service_method, success_message=MSG_QUERY_SUCCESS):
        body, error = self._body_or_error()
        if error:
            return error
        try:
            result = getattr(self._service(), service_method)(self._payload_from_body(body))
        except (UserError, ValidationError) as error:
            return self._business_error_response(error)
        except Exception:
            _logger.exception('REST API service call failed: %s', service_method)
            return self._error_response(500, MSG_SYSTEM_ERROR, status=500)
        return self._normalize_service_result(result, success_message=success_message)

    @http.route('/api/v1/auth/check', type='http', auth='public', methods=['POST'], csrf=False)
    def auth_check(self):
        return self._handle_payload_service('external_login_check', success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/panels/add', type='http', auth='public', methods=['POST'], csrf=False)
    def panels_add(self):
        return self._handle_payload_service('add_panel', success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/panels/query', type='http', auth='public', methods=['POST'], csrf=False)
    def panels_query(self):
        return self._handle_payload_service('query_panels')

    @http.route('/api/v1/panels/delete', type='http', auth='public', methods=['POST'], csrf=False)
    def panels_delete(self):
        return self._handle_payload_service('delete_panel', success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/manufacturing-orders/by-work-order', type='http', auth='public', methods=['POST'], csrf=False)
    def manufacturing_orders_by_work_order(self):
        return self._handle_payload_service('get_productions_by_work_order')

    @http.route('/api/v1/work-centers/search', type='http', auth='public', methods=['POST'], csrf=False)
    def work_centers_search(self):
        return self._handle_payload_service('get_workcenters_by_name')

    @http.route('/api/v1/defect-codes/search', type='http', auth='public', methods=['POST'], csrf=False)
    def defect_codes_search(self):
        return self._handle_payload_service('get_defect_codes_by_name')

    @http.route('/api/v1/laser/print-requests', type='http', auth='public', methods=['POST'], csrf=False)
    def laser_print_requests(self):
        body, error = self._body_or_error()
        if error:
            return error
        try:
            result = self._service().submit_laser_print_request(
                payload=body,
                source_system='LASER',
            )
        except (UserError, ValidationError) as error:
            return self._business_error_response(error)
        except Exception:
            _logger.exception('REST API laser print request failed.')
            return self._error_response(500, MSG_SYSTEM_ERROR, status=500)
        return self._normalize_service_result(result, success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/aoi/results', type='http', auth='public', methods=['POST'], csrf=False)
    def aoi_results(self):
        body, error = self._body_or_error()
        if error:
            return error
        try:
            result = self._service().submit_aoi_result(
                payload=body,
                workorder_id=None,
                source_system='AOI',
                override_route=False,
            )
        except (UserError, ValidationError) as error:
            return self._business_error_response(error)
        except Exception:
            _logger.exception('REST API AOI result failed.')
            return self._error_response(500, MSG_SYSTEM_ERROR, status=500)
        if isinstance(result, dict) and result.get('code') == 200:
            return self._json_response(result, status=201)
        return self._normalize_service_result(result, success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/online-context', type='http', auth='public', methods=['POST'], csrf=False)
    def online_context(self):
        body, error = self._body_or_error()
        if error:
            return error
        try:
            result = self._service().get_current_online_context(
                workcenter_id=self._as_int(body.get('workcenter_id') or body.get('workcenterId')),
                production_line_id=self._as_int(body.get('production_line_id') or body.get('productionLineId')),
                workshop_id=self._as_int(body.get('workshop_id') or body.get('workshopId')),
            )
        except (UserError, ValidationError) as error:
            return self._business_error_response(error)
        except Exception:
            _logger.exception('REST API online context failed.')
            return self._error_response(500, MSG_SYSTEM_ERROR, status=500)
        return self._normalize_service_result(result)

    @http.route('/api/v1/smt/loading/validate', type='http', auth='public', methods=['POST'], csrf=False)
    def smt_loading_validate(self):
        return self._handle_payload_service('smt_loading_validate')

    @http.route('/api/v1/smt/loading/save', type='http', auth='public', methods=['POST'], csrf=False)
    def smt_loading_save(self):
        return self._handle_payload_service('smt_loading_save', success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/workorders/scan-pass', type='http', auth='public', methods=['POST'], csrf=False)
    def workorder_scan_pass(self):
        body, error = self._body_or_error()
        if error:
            return error
        try:
            result = self._service().submit_scan_pass(
                payload=body,
                source_system='SCAN_PASS',
                override_route=self._as_bool(body.get('M_STR7')),
            )
        except (UserError, ValidationError) as error:
            return self._business_error_response(error)
        except Exception:
            _logger.exception('REST API workorder scan pass failed.')
            return self._error_response(500, MSG_SYSTEM_ERROR, status=500)
        return self._normalize_service_result(result, success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/workorders/events', type='http', auth='public', methods=['POST'], csrf=False)
    def workorder_events(self):
        body, error = self._body_or_error()
        if error:
            return error
        missing = []
        if not self._has_value(body, 'workorder_id', 'workorderId'):
            missing.append('workorder_id')
        if not self._has_value(body, 'event_type', 'eventType'):
            missing.append('event_type')
        if missing:
            return self._required_error(missing)
        try:
            result = self._service().submit_workorder_event(
                workorder_id=self._as_int(body.get('workorder_id') or body.get('workorderId')),
                event_type=body.get('event_type') or body.get('eventType'),
                serial_number=body.get('serial_number') or body.get('serialNumber'),
                operator_code=body.get('operator_code') or body.get('operatorCode'),
                note=body.get('note'),
                override_route=self._as_bool(body.get('override_route') or body.get('overrideRoute')),
                external_event_id=body.get('external_event_id') or body.get('externalEventId'),
                source_system=body.get('source_system') or body.get('sourceSystem'),
                payload=body.get('payload') if isinstance(body.get('payload'), dict) else body,
            )
        except (UserError, ValidationError) as error:
            return self._business_error_response(error)
        except Exception:
            _logger.exception('REST API workorder event failed.')
            return self._error_response(500, MSG_SYSTEM_ERROR, status=500)
        return self._normalize_service_result(result, success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/test-results', type='http', auth='public', methods=['POST'], csrf=False)
    def test_results(self):
        body, error = self._body_or_error()
        if error:
            return error
        missing = []
        if not self._has_value(body, 'workorder_id', 'workorderId'):
            missing.append('workorder_id')
        if not self._has_value(body, 'serial_number', 'serialNumber'):
            missing.append('serial_number')
        if missing:
            return self._required_error(missing)
        try:
            result = self._service().submit_test_result(
                workorder_id=self._as_int(body.get('workorder_id') or body.get('workorderId')),
                serial_number=body.get('serial_number') or body.get('serialNumber'),
                result=body.get('result') or 'pass',
                operator_code=body.get('operator_code') or body.get('operatorCode'),
                cycle_time_sec=body.get('cycle_time_sec') or body.get('cycleTimeSec'),
                basic_error=body.get('basic_error') or body.get('basicError'),
                phase_error=body.get('phase_error') or body.get('phaseError'),
                aging_temp_c=body.get('aging_temp_c') or body.get('agingTempC'),
                tester_channel=body.get('tester_channel') or body.get('testerChannel'),
                note=body.get('note'),
                payload=body.get('payload') if isinstance(body.get('payload'), dict) else body,
                external_event_id=body.get('external_event_id') or body.get('externalEventId'),
                source_system=body.get('source_system') or body.get('sourceSystem'),
            )
        except (UserError, ValidationError) as error:
            return self._business_error_response(error)
        except Exception:
            _logger.exception('REST API test result failed.')
            return self._error_response(500, MSG_SYSTEM_ERROR, status=500)
        return self._normalize_service_result(result, success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/finished-serials', type='http', auth='public', methods=['POST'], csrf=False)
    def finished_serials(self):
        body, error = self._body_or_error()
        if error:
            return error
        if not self._has_value(body, 'production_id', 'productionId'):
            return self._required_error(['production_id'])
        try:
            result = self._service().upload_finished_serials(
                production_id=self._as_int(body.get('production_id') or body.get('productionId')),
                serials=body.get('serials') or [],
                source_system=body.get('source_system') or body.get('sourceSystem'),
            )
        except (UserError, ValidationError) as error:
            return self._business_error_response(error)
        except Exception:
            _logger.exception('REST API finished serial upload failed.')
            return self._error_response(500, MSG_SYSTEM_ERROR, status=500)
        return self._normalize_service_result(result, success_message=MSG_SAVE_SUCCESS)

    @http.route('/api/v1/serials/trace', type='http', auth='public', methods=['POST'], csrf=False)
    def serial_trace(self):
        body, error = self._body_or_error()
        if error:
            return error
        if not self._has_value(body, 'serial_number', 'serialNumber'):
            return self._required_error(['serial_number'])
        try:
            result = self._service().get_serial_trace(
                serial_number=body.get('serial_number') or body.get('serialNumber'),
                include_test_results=self._as_bool(body.get('include_test_results', body.get('includeTestResults', True))),
                travel_limit=self._as_int(body.get('travel_limit') or body.get('travelLimit')) or 50,
                test_result_limit=self._as_int(body.get('test_result_limit') or body.get('testResultLimit')) or 50,
            )
        except (UserError, ValidationError) as error:
            return self._business_error_response(error)
        except Exception:
            _logger.exception('REST API serial trace failed.')
            return self._error_response(500, MSG_SYSTEM_ERROR, status=500)
        return self._normalize_service_result(result)
