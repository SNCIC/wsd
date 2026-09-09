import logging
import time

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.sn_wsd_api.models.api_scan_pass import (
    ApiBadRequest,
    ApiForbidden,
    ApiNotFound,
    ApiUnauthorized,
)

_logger = logging.getLogger(__name__)


class SnWsdDeviceApi(http.Controller):
    """Device-facing endpoints: plain JSON POST, no authentication. The
    company scope comes from the payload (M_DATA_AUTH, or the work center
    for AOI). Error messages render in Chinese; the status code grades the
    failure (400 payload / 404 missing / 422 business rule / 500 system)."""

    def _logged_call(self, endpoint, service_method, payload,
                     success_message='OK'):
        """Run one device call inside a full raw request/response log."""
        start = time.time()
        base_vals = {
            'endpoint': endpoint,
            'workcenter_code': (
                payload.get('M_WORK_STATIONSN') or payload.get('machineName')),
            'employee_code': payload.get('M_EMP') or payload.get('operator'),
            'sn': payload.get('M_SN') or payload.get('productSn'),
            'test_result': (
                (payload.get('M_TEST_RESULT') or payload.get('stationResult') or '')
                .strip().lower() or None),
            'payload': payload,
        }

        def log(values):
            request.env['sn.wsd.api.request.log'].sudo().create(
                {**base_vals, **values})

        def log_failure(code, message):
            # the business rollback wiped any in-flight rows, so failure
            # records persist through their own cursor
            with request.registry.cursor() as log_cr:
                request.env(cr=log_cr)[
                    'sn.wsd.api.request.log'].sudo().create({**base_vals,
                        'result_code': str(code),
                        'result_message': message,
                        'duration_ms': int((time.time() - start) * 1000)})

        def fail(code, message):
            log_failure(code, message)
            return {'code': code, 'message': message, 'data': False}

        try:
            data = service_method(payload)
            log({
                'result_code': '200',
                'result_message': 'OK',
                'response': data,
                'duration_ms': int((time.time() - start) * 1000),
            })
            request.env.cr.commit()
            return {'code': 200, 'message': success_message, 'data': data}
        except ApiBadRequest as error:
            request.env.cr.rollback()
            return fail(400, str(error))
        except ApiUnauthorized as error:
            request.env.cr.rollback()
            return fail(401, str(error))
        except ApiForbidden as error:
            request.env.cr.rollback()
            return fail(403, str(error))
        except ApiNotFound as error:
            request.env.cr.rollback()
            return fail(404, str(error))
        except ValidationError as error:
            # ApiUnprocessable and ungraded business rejections
            request.env.cr.rollback()
            return fail(422, str(error))
        except Exception as error:  # noqa: BLE001 - devices need a JSON body
            request.env.cr.rollback()
            _logger.exception('device api %s failed', endpoint)
            return fail(500, str(error))

    def _body_or_error(self):
        """Raw JSON object body, or a uniform 400 response."""
        try:
            data = request.get_json_data()
        except (ValueError, TypeError):
            data = None
        if not isinstance(data, dict):
            return None, request.make_json_response(
                {'code': 400, 'message': 'invalid json body', 'data': False},
                status=400)
        return dict(data), None

    def _respond(self, result):
        status = result.get('code', 200) if isinstance(result, dict) else 200
        return request.make_json_response(result, status=status)

    def _service(self):
        return request.env['sn.wsd.api.service'].sudo().with_context(
            lang='zh_CN')

    @http.route('/api/v1/workorders/scan-pass', type='http', auth='public',
                methods=['POST'], csrf=False)
    def scan_pass(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        return self._respond(self._logged_call(
            '/api/v1/workorders/scan-pass', self._service().scan_pass,
            payload))

    @http.route('/api/v1/next-sn', type='http', auth='public',
                methods=['POST'], csrf=False)
    def next_sn(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        return self._respond(self._logged_call(
            '/api/v1/next-sn', self._service().request_next_sn, payload))

    @http.route('/api/v1/aoi/results', type='http', auth='public',
                methods=['POST'], csrf=False)
    def aoi_results(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        result = self._logged_call(
            '/api/v1/aoi/results', self._service().submit_aoi_result,
            payload, success_message='success')
        if result.get('code') == 200:
            # device contract: 201 + empty data object on success
            result['data'] = {}
            return request.make_json_response(result, status=201)
        return self._respond(result)

    @http.route('/api/v1/laser/print-requests', type='http', auth='public',
                methods=['POST'], csrf=False)
    def laser_print_requests(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        return self._respond(self._logged_call(
            '/api/v1/laser/print-requests',
            self._service().submit_laser_print_request, payload))

    @http.route('/api/v1/auth/check', type='http', auth='public',
                methods=['POST'], csrf=False)
    def auth_check(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        # the raw password travels only to the service; the request log
        # keeps a redacted copy of the payload
        credential = {'password': payload.get('password') or ''}
        redacted = dict(payload)
        if redacted.get('password'):
            redacted['password'] = '***'
        return self._respond(self._logged_call(
            '/api/v1/auth/check',
            lambda p: self._service().auth_check(p, credential),
            redacted))

    @http.route('/api/v1/manufacturing-orders/by-work-order', type='http',
                auth='public', methods=['POST'], csrf=False)
    def mes_orders_by_work_order(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        return self._respond(self._logged_call(
            '/api/v1/manufacturing-orders/by-work-order',
            self._service().search_mes_orders, payload,
            success_message='success'))

    @http.route('/api/v1/work-centers/search', type='http', auth='public',
                methods=['POST'], csrf=False)
    def work_centers_search(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        return self._respond(self._logged_call(
            '/api/v1/work-centers/search',
            self._service().search_work_centers, payload,
            success_message='success'))

    @http.route('/api/v1/defect-codes/search', type='http', auth='public',
                methods=['POST'], csrf=False)
    def defect_codes_search(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        return self._respond(self._logged_call(
            '/api/v1/defect-codes/search',
            self._service().search_defect_codes, payload,
            success_message='success'))
