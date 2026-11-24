import json
import secrets
import string
import time

import pytz
import requests

from odoo import api, fields, models

EIP_TIMEZONE = pytz.timezone('Asia/Shanghai')
_TRANSNO_ALPHABET = string.digits + string.ascii_letters
_TRANSNO_RANDOM_LENGTH = 6
_SUCCESS_STATUS = '00000'
# Status codes the spec documents as platform-side failures (system
# timeout / system error): worth retrying, unlike 1xxxx / 2xxxx data
# errors.
_RETRYABLE_STATUSES = frozenset({'90001', '90003'})
_PAGING_KEYS = ('pageNum', 'pageSize', 'pageCount', 'total')
MAX_LOG_TEXT = 50000
_ERROR_SNIPPET = 500


def _truncate(text, limit=MAX_LOG_TEXT):
    text = text or ''
    if len(text) <= limit:
        return text
    return '%s\n... [truncated %s characters]' % (text[:limit], len(text) - limit)


class EipTransport(models.AbstractModel):
    """Single outbound exit towards the EIP platform (spec V8.0.14).

    Every call is one HTTP POST with the three header fields
    (orisys / transno / operatetype) as HTTP request headers and a pure
    JSON body; no authentication is attached (user decision 2026-11-24).
    The result is always a plain dict: transport and business failures
    are reported in it instead of being raised, so no call site can
    forget to log a failure.
    """

    _name = 'sn.wsd.eip.transport'
    _description = 'EIP HTTP Transport'

    @api.model
    def _eip_result(self, **values):
        """Return a call result prefilled with "failed, no detail"."""
        result = {
            'success': False,
            'status': '',
            'message': '',
            'data': None,
            'page_info': {},
            'transno': '',
            'http_status': None,
            'raw': '',
            'error': '',
            'retryable': False,
            'log_id': False,
        }
        result.update(values)
        return result

    @api.model
    def _eip_beijing(self, value):
        """Convert a UTC naive datetime (an ORM Datetime value) to the
        Beijing wall-clock naive datetime the platform expects."""
        return pytz.utc.localize(value).astimezone(EIP_TIMEZONE).replace(
            tzinfo=None)

    @api.model
    def _eip_now(self):
        return self._eip_beijing(fields.Datetime.now())

    @api.model
    def _eip_format_datetime(self, value):
        """``yyyy-MM-dd HH:mm:ss`` in Beijing time; empty stays empty."""
        if not value:
            return ''
        return self._eip_beijing(value).strftime('%Y-%m-%d %H:%M:%S')

    @api.model
    def _eip_format_date(self, value):
        """``yyyy-MM-dd``; dates carry no timezone."""
        if not value:
            return ''
        return value.strftime('%Y-%m-%d')

    @api.model
    def _eip_transno(self):
        """Global transaction number: Beijing time yyyyMMddHHmmssSSS
        followed by 6 random digits/letters (spec appendix)."""
        random_part = ''.join(
            secrets.choice(_TRANSNO_ALPHABET)
            for _ in range(_TRANSNO_RANDOM_LENGTH))
        return self._eip_now().strftime('%Y%m%d%H%M%S%f')[:17] + random_part

    @api.model
    def _eip_truthy(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ('true', '1')
        return bool(value)

    @api.model
    def _eip_norm_status(self, value):
        """Normalise the EIP status to a 5-character string: the spec
        declares it Int but every sample shows "00000"."""
        if value is None:
            return ''
        status = str(value).strip()
        if status.isdigit():
            status = status.zfill(5)
        return status

    @api.model
    def _eip_to_int(self, value):
        if value is None or value == '':
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

    @api.model
    def _eip_page_info(self, result_value):
        """Paging info lives in resultValue.pageInfo in the samples but
        is drawn flat in the parameter table: accept both shapes, and
        accept numbers or numeric strings."""
        source = result_value.get('pageInfo')
        if not isinstance(source, dict):
            source = result_value
        return {key: self._eip_to_int(source.get(key)) for key in _PAGING_KEYS}

    @api.model
    def _eip_parse_response(self, raw, http_status):
        """Tolerant parsing of a response body into a call result."""
        result = self._eip_result(raw=raw or '', http_status=http_status)
        snippet = _truncate(raw or '', _ERROR_SNIPPET)
        if http_status is None:
            return dict(result, error='No response from the EIP platform.',
                        retryable=True)
        if http_status >= 300:
            return dict(
                result,
                error='HTTP %s: %s' % (http_status, snippet),
                retryable=http_status >= 500)
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return dict(result, error='Non-JSON response: %s' % snippet,
                        retryable=True)
        if not isinstance(payload, dict) or 'successful' not in payload:
            return dict(result, error='Unexpected response: %s' % snippet,
                        retryable=True)
        result_value = payload.get('resultValue')
        if not isinstance(result_value, dict):
            result_value = {}
        status = self._eip_norm_status(result_value.get('status'))
        message = result_value.get('message') or payload.get('resultHint') or ''
        result.update(
            status=status,
            message=message if isinstance(message, str) else str(message),
            data=result_value.get('data'),
            page_info=self._eip_page_info(result_value),
        )
        if (self._eip_truthy(payload.get('successful'))
                and status == _SUCCESS_STATUS):
            return dict(result, success=True)
        return dict(
            result,
            error='EIP %s: %s' % (status or '???', result['message'] or 'unsuccessful response'),
            retryable=status in _RETRYABLE_STATUSES,
        )

    @api.model
    def _eip_log_model(self, interface):
        return ('sn.wsd.eip.pull.log' if interface.direction == 'pull'
                else 'sn.wsd.eip.push.log')

    @api.model
    def _eip_open_log(self, config, interface, operatetype, body, extra=None):
        """Create the log row of one call in state "sending" and return
        it. The request is sent by ``_eip_send``; the pull engine puts
        a commit between the two so the call is durably counted before
        it leaves."""
        Log = self.env[self._eip_log_model(interface)]
        transno = self._eip_transno()
        headers = {
            'orisys': '0',
            'transno': transno,
            'operatetype': operatetype,
        }
        values = {
            'company_id': config.company_id.id,
            'config_id': config.id,
            'interface_id': interface.id,
            'operatetype': operatetype,
            'transno': transno,
            'request_headers': json.dumps(headers, ensure_ascii=False),
            'request_body': json.dumps(body or {}, ensure_ascii=False),
            'result': 'sending',
            'start_at': fields.Datetime.now(),
        }
        for key, value in (extra or {}).items():
            if key in Log._fields:
                values[key] = value
        return Log.create(values)

    @api.model
    def _eip_send(self, log, body):
        """POST ``body`` as prepared on ``log``, write the outcome on the
        log row and return the call result. Never raises."""
        config = log.config_id
        interface = log.interface_id
        headers = json.loads(log.request_headers or '{}')
        headers['Content-Type'] = 'application/json; charset=utf-8'
        url = (config.base_url or '').rstrip('/') + (interface.path or '')
        payload = json.dumps(body or {}, ensure_ascii=False).encode('utf-8')
        started = time.time()
        try:
            response = requests.post(
                url, data=payload, headers=headers,
                timeout=config.timeout_sec)
            raw = response.content.decode('utf-8', errors='replace')
            result = self._eip_parse_response(raw, response.status_code)
        except requests.RequestException as exc:
            result = self._eip_result(
                error=str(exc) or type(exc).__name__, retryable=True)
        log.write({
            'response_body': _truncate(result['raw']),
            'http_status': result['http_status'],
            'status_code': result['status'],
            'status_message': result['message'],
            'result': 'success' if result['success'] else 'failed',
            'error': result['error'],
            'duration_ms': int(round((time.time() - started) * 1000)),
            'end_at': fields.Datetime.now(),
        })
        result['transno'] = log.transno
        result['log_id'] = log.id
        return result

    @api.model
    def _eip_call(self, config, interface, operatetype, body, extra=None):
        """Open the log and send in one go (the push engine)."""
        log = self._eip_open_log(config, interface, operatetype, body, extra)
        return self._eip_send(log, body)
