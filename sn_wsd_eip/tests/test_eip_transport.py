"""Batch 2 of the eip-order-push change: HTTP transport envelope.

Covers the "HTTP 传输信封", "响应解析与成功判定" and "调用留痕"
requirements of the eip-integration-config spec.
"""

import datetime
import json
import re
import socket
from unittest.mock import patch

import pytz
import requests

from odoo import fields
from odoo.tests import common as test_common
from odoo.tests import tagged

from .eip_order_common import EipOrderCase, eip_envelope

_TRANSNO_PATTERN = re.compile(r'^\d{17}[0-9A-Za-z]{6}$')
_BEIJING = pytz.timezone('Asia/Shanghai')


@tagged('post_install', '-at_install')
class TestEipTransport(EipOrderCase):

    def _call(self, body=None, code='sale_order', operatetype='ADD'):
        return self.transport._eip_call(
            self.config, self.interface(code), operatetype, body or {})

    # ------------------------------------------------------------------
    # request shape: headers, pure JSON body, no authentication
    # ------------------------------------------------------------------

    def test_10_request_shape(self):
        self.server.enqueue(eip_envelope(data='0500626736'))
        body = {'ipoNo': 'IPO001', 'amount': '200'}
        result = self._call(body)
        self.assertTrue(result['success'], result)
        request = self.last_request()
        self.assertEqual(request['path'], '/api/supplier-so')
        headers = request['headers']
        self.assertEqual(headers['orisys'], '0')
        self.assertEqual(headers['operatetype'], 'ADD')
        self.assertRegex(headers['transno'], _TRANSNO_PATTERN)
        self.assertEqual(headers['transno'], result['transno'])
        self.assertNotIn('authorization', headers)
        self.assertTrue(
            headers['content-type'].startswith('application/json'))
        self.assertEqual(request['json'], body)

    def test_20_transno_format_and_uniqueness(self):
        transnos = [self.transport._eip_transno() for _ in range(1000)]
        self.assertEqual(len(set(transnos)), 1000)
        now = pytz.utc.localize(fields.Datetime.now())
        beijing_now = now.astimezone(_BEIJING).replace(tzinfo=None)
        for transno in transnos:
            self.assertRegex(transno, _TRANSNO_PATTERN)
            # first 14 digits are the Beijing wall-clock time: a UTC stamp
            # would be eight hours away
            stamped = datetime.datetime.strptime(
                transno[:14], '%Y%m%d%H%M%S')
            self.assertLess(abs((beijing_now - stamped).total_seconds()), 120)

    def test_30_chinese_not_escaped(self):
        name = '三相电能表'
        self._call({'materialsName': name})
        raw = self.last_request()['raw']
        self.assertIn(name.encode('utf-8'), raw)
        self.assertNotIn(b'\\u', raw)

    # ------------------------------------------------------------------
    # response parsing: success, numeric status, business failure,
    # non-JSON, platform error
    # ------------------------------------------------------------------

    def test_40_parse_success(self):
        self.server.enqueue(eip_envelope(data='0500626736', message='成功'))
        result = self._call({'ipoNo': 'IPO001'})
        self.assertTrue(result['success'], result)
        self.assertEqual(result['status'], '00000')
        self.assertEqual(result['message'], '成功')
        self.assertEqual(result['data'], '0500626736')
        self.assertFalse(result['error'])
        self.assertEqual(result['http_status'], 200)

    def test_41_numeric_status_is_success(self):
        payload = eip_envelope(data=[])
        payload['resultValue']['status'] = 0
        self.server.enqueue(payload)
        result = self._call({})
        self.assertTrue(result['success'], result)
        self.assertEqual(result['status'], '00000')

    def test_42_business_failure(self):
        self.server.enqueue(eip_envelope(
            status='20006', message='重复推送数据'))
        result = self._call({})
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], '20006')
        self.assertEqual(result['message'], '重复推送数据')
        self.assertFalse(result['retryable'])

    def test_43_non_json_response(self):
        self.server.enqueue(
            b'<html><body>Bad Gateway</body></html>', http_status=502)
        result = self._call({})
        self.assertFalse(result['success'])
        self.assertEqual(result['http_status'], 502)
        self.assertIn('HTTP 502', result['error'])
        self.assertIn('Bad Gateway', result['error'])

    def test_44_platform_error_is_retryable(self):
        self.server.enqueue(eip_envelope(
            status='90001', message='系统超时', successful=False))
        result = self._call({})
        self.assertFalse(result['success'])
        self.assertTrue(result['retryable'])

    def test_45_unsuccessful_flag_blocks(self):
        payload = eip_envelope(data='X', successful=False)
        result = self.transport._eip_parse_response(json.dumps(payload), 200)
        self.assertFalse(result['success'])
        self.assertFalse(result['retryable'])

    # ------------------------------------------------------------------
    # paging info: nested or flat, numbers or strings
    # ------------------------------------------------------------------

    def test_46_page_info_nested_and_flat(self):
        nested = {'successful': True, 'resultValue': {
            'status': '00000', 'data': [],
            'pageInfo': {'pageNum': '1', 'pageSize': '1000',
                         'pageCount': '0', 'total': ''}}}
        result = self.transport._eip_parse_response(json.dumps(nested), 200)
        self.assertTrue(result['success'])
        self.assertEqual(result['page_info'], {
            'pageNum': 1, 'pageSize': 1000, 'pageCount': 0, 'total': None})
        flat = {'successful': True, 'resultValue': {
            'status': 0, 'data': [], 'pageNum': 2,
            'pageSize': 1000, 'pageCount': 5, 'total': 4500}}
        result = self.transport._eip_parse_response(json.dumps(flat), 200)
        self.assertTrue(result['success'])
        self.assertEqual(result['page_info'], {
            'pageNum': 2, 'pageSize': 1000, 'pageCount': 5, 'total': 4500})

    # ------------------------------------------------------------------
    # one log row per call, in the log of the interface direction
    # ------------------------------------------------------------------

    def test_50_push_call_logged(self):
        self.server.enqueue(eip_envelope(data='OK'))
        result = self._call({'ipoNo': 'IPO001'}, code='production_order')
        PushLog = self.env['sn.wsd.eip.push.log']
        self.assertEqual(PushLog.search_count([]), 1)
        log = PushLog.browse(result['log_id'])
        self.assertEqual(log.result, 'success')
        self.assertEqual(log.transno, result['transno'])
        self.assertEqual(log.interface_id.code, 'production_order')
        self.assertEqual(log.operatetype, 'ADD')
        self.assertEqual(json.loads(log.request_headers)['orisys'], '0')
        self.assertEqual(json.loads(log.request_body), {'ipoNo': 'IPO001'})
        self.assertEqual(
            json.loads(log.response_body)['resultValue']['data'], 'OK')
        self.assertEqual(log.status_code, '00000')
        self.assertEqual(log.http_status, 200)
        self.assertGreaterEqual(log.duration_ms, 0)
        self.assertEqual(log.company_id, self.config.company_id)

    def test_51_pull_call_logged_in_pull_log(self):
        self.server.enqueue(eip_envelope(
            data=[],
            pageInfo={'pageNum': '1', 'pageSize': '1000',
                      'pageCount': '1', 'total': '2'}))
        result = self._call({'pageNum': 1, 'pageSize': 1000},
                            code='purchase_order', operatetype='QUERY')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['page_info']['pageCount'], 1)
        request = self.last_request()
        self.assertEqual(request['headers']['operatetype'], 'QUERY')
        self.assertEqual(request['path'], '/api/supplier-send')
        self.assertEqual(self.env['sn.wsd.eip.pull.log'].search_count([]), 1)
        self.assertEqual(self.env['sn.wsd.eip.push.log'].search_count([]), 0)
        log = self.env['sn.wsd.eip.pull.log'].browse(result['log_id'])
        self.assertEqual(log.result, 'success')

    # ------------------------------------------------------------------
    # network failures: reported, logged, never raised
    # ------------------------------------------------------------------

    def test_60_timeout_does_not_raise(self):
        # Odoo's test framework raises every request timeout below 10s to
        # 10s (BaseCase._request_handler). Send this one request through
        # the genuine Session.send so the configured 1s timeout applies.
        self.config.write({'timeout_sec': 1})
        self.server.enqueue(delay=3)
        with patch.object(requests.sessions.Session, 'send',
                          test_common._super_send):
            result = self._call({})
        self.assertFalse(result['success'])
        self.assertTrue(result['retryable'])
        self.assertIn('timed out', result['error'].lower())
        log = self.env['sn.wsd.eip.push.log'].browse(result['log_id'])
        self.assertEqual(log.result, 'failed')
        self.assertIn('timed out', log.error.lower())

    def test_61_connection_error_does_not_raise(self):
        # a port nobody listens on
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        closed_port = probe.getsockname()[1]
        probe.close()
        self.config.write({'base_url': 'http://127.0.0.1:%s' % closed_port})
        result = self._call({})
        self.assertFalse(result['success'])
        self.assertTrue(result['retryable'])
        self.assertTrue(result['error'])
        log = self.env['sn.wsd.eip.push.log'].browse(result['log_id'])
        self.assertEqual(log.result, 'failed')
        self.assertFalse(log.http_status)

    def test_62_configured_timeout_is_forwarded(self):
        # the test framework overrides small timeouts on real requests, so
        # check on a stand-in that the config value reaches requests and
        # that a read timeout is reported, not raised
        self.config.write({'timeout_sec': 7})
        seen = {}

        def fake_post(url, **kwargs):
            seen.update(kwargs)
            raise requests.exceptions.ReadTimeout(
                'Read timed out. (read timeout=7)')
        with patch.object(requests, 'post', fake_post):
            result = self._call({'ipoNo': 'IPO001'})
        self.assertEqual(seen['timeout'], 7)
        self.assertEqual(seen['headers']['operatetype'], 'ADD')
        self.assertFalse(result['success'])
        self.assertTrue(result['retryable'])
        self.assertIn('timed out', result['error'])
