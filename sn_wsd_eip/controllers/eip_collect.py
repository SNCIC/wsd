"""Gateway-facing endpoints of the production-data collection service.

Contract (fixed, the EIP gateway depends on it -- do not translate):
    POST /api/eip/collect/<code>
    amount (positive int): in the JSON body {"amount": N} or on the
        query string ?amount=N (the spec shows the parameter but not
        where it rides -- both are accepted, body wins)
    reply (HTTP 200, the spec status field carries the outcome):
        {"status": 0, "message": "", "supplierCode": "...", "data": [...]}
    failures use the same shape with "status": 1 and an English message.
"""
import json
import logging

from odoo import http
from odoo.http import request

from ..models.eip_collect_interface import EipCollectError

_logger = logging.getLogger(__name__)

# hard cap on the per-fetch record count, guarding the server against a
# runaway amount (the gateway adjusts its own frequency by the returned
# count, so small answers are fine)
MAX_AMOUNT = 1000


class EipCollectController(http.Controller):
    """Login-free endpoints the EIP gateway polls (LAN-isolated)."""

    # Odoo 19 defaults auth='none' routes to a readonly cursor; this
    # endpoint delivers (flips states), so readonly=False is mandatory.
    @http.route('/api/eip/collect/<string:code>', type='http',
                auth='none', methods=['POST'], csrf=False, readonly=False)
    def collect(self, code, **kwargs):
        try:
            body = json.loads(request.httprequest.get_data() or b'{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None  # tolerate: the amount may ride the query string
        if body is not None and not isinstance(body, dict):
            return self._error(code, None, 'json body must be an object')
        amount = body.get('amount') if isinstance(body, dict) else None
        if amount is None and kwargs.get('amount') is not None:
            try:
                amount = int(str(kwargs['amount']).strip())
            except (TypeError, ValueError):
                amount = None
        if isinstance(amount, bool) \
                or not isinstance(amount, int) or amount < 1:
            return self._error(
                code, None,
                'missing or invalid amount, expected a positive integer')
        amount = min(amount, MAX_AMOUNT)
        try:
            result = request.env[
                'sn.wsd.eip.collect.interface'].sudo()._eip_serve(
                code, amount)
        except EipCollectError as error:
            return self._error(code, amount, str(error))
        except Exception:  # noqa: BLE001 -- never leak a traceback
            _logger.exception('EIP collect endpoint %s failed', code)
            return self._error(
                code, amount, 'internal error; see server log')
        self._log(code, amount, len(result['data']), 'success', None)
        return request.make_json_response({
            'status': 0,
            'message': '',
            'supplierCode': result['supplier_code'],
            'data': result['data'],
        })

    def _error(self, code, amount, message):
        """Protocol failure: status-1 envelope (HTTP stays 200 -- the
        gateway reads the body), fetch log stamped."""
        self._log(code, amount or 0, 0, 'error', message)
        return request.make_json_response({
            'status': 1,
            'message': message,
            'supplierCode': '',
            'data': [],
        })

    def _log(self, code, amount, returned, state, error_message):
        """Stamp the fetch log; a logging failure must never break the
        reply (and the transaction may already be aborted on the error
        paths)."""
        try:
            company = request.env['res.company'].sudo().search(
                [], order='id asc', limit=1)
            request.env['sn.wsd.eip.collect.log'].sudo().create({
                'company_id': company.id,
                'code': code or '',
                'amount': amount or 0,
                'returned': returned or 0,
                'source': request.httprequest.remote_addr or '',
                'state': state,
                'error_message': error_message,
            })
        except Exception:  # noqa: BLE001 -- log is best-effort
            _logger.warning('EIP collect fetch log write failed',
                            exc_info=True)
