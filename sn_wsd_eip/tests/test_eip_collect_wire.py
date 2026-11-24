"""Wire contract of /api/eip/collect/<code> (HTTP level, error paths).

The happy path cannot run over HTTP here: fixtures created in the test
transaction are invisible to the endpoint's own transaction (tests may
not commit), so the serving semantics are covered ORM-level in
``test_eip_collect_serve``. These cases exercise the real route, JSON
parsing and request validation -- every rejection answers before any
fixture lookup, and the fetch log row of a rejected call commits with
the request.
"""

import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestEipCollectWire(HttpCase):
    """POST /api/eip/collect/<code> wire failures answer status 1."""

    def _post(self, path='/api/eip/collect/1002', body=None, raw=None):
        data = raw if raw is not None else json.dumps(body or {})
        return self.url_open(
            path, data=data, headers={'Content-Type': 'application/json'})

    def test_10_rejects_non_json_body(self):
        res = self._post(raw='not-json')
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body['status'], 1)
        self.assertIn('json', body['message'])

    def test_20_rejects_bad_amount(self):
        for payload in ({}, {'amount': 0}, {'amount': 'ten'},
                        {'amount': True}):
            res = self._post(body=payload)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()['status'], 1)
            self.assertIn('amount', res.json()['message'])

    def test_30_unknown_code_is_rejected_and_logged(self):
        res = self._post(path='/api/eip/collect/9999', body={'amount': 5})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body['status'], 1)
        self.assertIn('unknown or disabled', body['message'])
        self.assertEqual(body['data'], [])
        log = self.env['sn.wsd.eip.collect.log'].search(
            [('code', '=', '9999')], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.state, 'error')
        self.assertIn('unknown or disabled', log.error_message)
