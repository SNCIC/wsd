"""NQI gateway callback endpoint.

The gateway parses uploaded batches asynchronously and reports the
outcome by notice number: {"noticeNo", "return_flag" (1 ok / 0 fail),
"return_msg"}. The transport is unrestricted per the spec; we accept
JSON or form-encoded POSTs. No token check (removed by decision): the
endpoint only carries notice-number outcome flags.
"""
import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class NqiCallbackController(http.Controller):

    @http.route(
        '/nqi/callback', type='http', auth='public', methods=['POST'],
        csrf=False)
    def nqi_callback(self, **kwargs):
        try:
            payload = request.get_json_data()
        except Exception:  # noqa: BLE001 -- not JSON: form fallback
            payload = {}
        # form-encoded fallback (the gateway method is unrestricted)
        for key in ('noticeNo', 'notice_no', 'return_flag', 'return_msg'):
            if not payload.get(key):
                payload[key] = request.httprequest.form.get(key, '')
        notice_no = payload.get('noticeNo') or payload.get('notice_no')
        return_flag = payload.get('return_flag')
        if not notice_no or return_flag in (None, ''):
            return request.make_json_response({
                'return_flag': '0', 'return_msg': 'missing parameters'})
        try:
            request.env['sn.wsd.nqi.push.log'].sudo().process_callback(
                notice_no, return_flag, payload.get('return_msg', ''))
        except Exception as exc:  # noqa: BLE001
            _logger.warning('NQI callback processing failed: %s', exc)
            return request.make_json_response({
                'return_flag': '0', 'return_msg': str(exc)})
        return request.make_json_response({
            'return_flag': '1', 'return_msg': 'received'})
