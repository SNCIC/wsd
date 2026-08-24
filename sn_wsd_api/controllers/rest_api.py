import logging
import time

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _check_token():
    token = request.httprequest.headers.get('X-API-Token', '')
    expected = request.env['ir.config_parameter'].sudo().get_param(
        'sn_wsd_api.token')
    if not expected or token != expected:
        return False
    return True


class SnWsdDeviceApi(http.Controller):

    def _logged_call(self, endpoint, service_method, payload):
        """Run one device call inside a full raw request/response log."""
        start = time.time()
        log = request.env['sn.wsd.api.request.log'].sudo().create({
            'endpoint': endpoint,
            'workcenter_code': payload.get('M_WORK_STATIONSN'),
            'employee_code': payload.get('M_EMP'),
            'sn': payload.get('M_SN'),
            'test_result': (
                (payload.get('M_TEST_RESULT') or '').strip().lower()
                or None),
            'payload': payload,
        })
        try:
            data = service_method(payload)
            log.sudo().write({
                'result_code': '200',
                'result_message': 'OK',
                'response': data,
                'duration_ms': int((time.time() - start) * 1000),
            })
            request.env.cr.commit()
            return {'code': 200, 'message': 'OK', 'data': data}
        except ValidationError as error:
            request.env.cr.rollback()
            message = str(error)
            log.sudo().write({
                'result_code': '400',
                'result_message': message,
                'duration_ms': int((time.time() - start) * 1000),
            })
            request.env.cr.commit()
            return {'code': 400, 'message': message, 'data': False}
        except Exception as error:  # noqa: BLE001 - devices need a JSON body
            request.env.cr.rollback()
            _logger.exception('device api %s failed', endpoint)
            message = str(error)
            log.sudo().write({
                'result_code': '500',
                'result_message': message,
                'duration_ms': int((time.time() - start) * 1000),
            })
            request.env.cr.commit()
            return {'code': 500, 'message': message, 'data': False}

    @http.route('/api/v1/scan-pass', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def scan_pass(self, **kwargs):
        if not _check_token():
            return {'code': 401, 'message': 'Unauthorized', 'data': False}
        payload = dict(request.get_json_data() or {})
        service = request.env['sn.wsd.api.service'].sudo().with_company(
            request.env.company)
        return self._logged_call(
            '/api/v1/scan-pass', service.scan_pass, payload)

    @http.route('/api/v1/next-sn', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def next_sn(self, **kwargs):
        if not _check_token():
            return {'code': 401, 'message': 'Unauthorized', 'data': False}
        payload = dict(request.get_json_data() or {})
        service = request.env['sn.wsd.api.service'].sudo().with_company(
            request.env.company)
        return self._logged_call(
            '/api/v1/next-sn', service.request_next_sn, payload)

