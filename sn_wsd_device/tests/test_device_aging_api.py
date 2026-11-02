import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestDeviceAgingApi(HttpCase):
    """POST /api/device/aging wire contract: one temperature point per
    packet, same shell as the reflow/wave zone endpoints."""

    def _post(self, body):
        return self.url_open(
            '/api/device/aging', data=body,
            headers={'Content-Type': 'application/json'})

    def test_10_push_point(self):
        res = self._post(json.dumps({
            'device_sn': 'AGE-TEST-01',
            'collect_time': '2026-11-02T08:30:00',
            'temperature': 70.5,
        }))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {'code': 200, 'message': 'Saved successfully'})
        record = self.env['sn.wsd.device.aging.record'].search([
            ('device_sn', '=', 'AGE-TEST-01')], limit=1)
        self.assertTrue(record)
        self.assertEqual(record.temperature, 70.5)

    def test_20_validation(self):
        # non-JSON body
        res = self._post('not-json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 400)
        # missing device_sn
        res = self._post(json.dumps({
            'collect_time': '2026-11-02T08:30:00', 'temperature': 70.5}))
        self.assertEqual(res.status_code, 400)
        self.assertIn('device_sn', res.json()['message'])
        # invalid collect_time
        res = self._post(json.dumps({
            'device_sn': 'AGE-TEST-01',
            'collect_time': 'not-a-date', 'temperature': 70.5}))
        self.assertEqual(res.status_code, 400)
        self.assertIn('collect_time', res.json()['message'])
        # non-numeric temperature
        res = self._post(json.dumps({
            'device_sn': 'AGE-TEST-01',
            'collect_time': '2026-11-02T08:30:00',
            'temperature': 'hot'}))
        self.assertEqual(res.status_code, 400)
        self.assertIn('temperature', res.json()['message'])
