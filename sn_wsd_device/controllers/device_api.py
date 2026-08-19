import json
from datetime import datetime, timezone

from odoo import http
from odoo.http import request

# Limits guarding the public endpoints against malformed payloads.
MAX_ZONES = 100
MAX_ZONE_NAME_LEN = 64


class DeviceDataController(http.Controller):
    """Login-free endpoints for shop-floor devices pushing collected data.

    Contract (fixed, devices depend on it -- do not translate):
        POST /api/device/reflow  -> reflow soldering packets
        POST /api/device/wave    -> wave soldering packets
        body:  {"device_sn": str, "collect_time": ISO datetime, "zones": {name: number}}
        200 -> {"code": 200, "message": "保存成功"}
        400 -> {"code": 400, "message": "<english reason>"}
    """

    @http.route('/api/device/reflow', type='http', auth='none',
                methods=['POST'], csrf=False)
    def receive_reflow_data(self, **kwargs):
        return self._receive_zone_packet('sn.wsd.device.reflow.record')

    @http.route('/api/device/wave', type='http', auth='none',
                methods=['POST'], csrf=False)
    def receive_wave_data(self, **kwargs):
        return self._receive_zone_packet('sn.wsd.device.wave.record')

    def _receive_zone_packet(self, model):
        """Validate a zone-temperature packet and store it on `model`.

        Both target models expose the same field names (device_sn,
        collect_time, zone_line_ids -> zone_name/temperature), which keeps
        this helper independent of the soldering technology.
        """
        try:
            payload = json.loads(request.httprequest.get_data() or b'{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._error(400, 'invalid json body, expected utf-8 json')
        if not isinstance(payload, dict):
            return self._error(400, 'json body must be an object')

        device_sn = str(payload.get('device_sn') or '').strip()
        if not device_sn:
            return self._error(400, 'missing device_sn')

        collect_dt = self._parse_collect_time(payload.get('collect_time'))
        if collect_dt is None:
            return self._error(
                400, 'invalid collect_time, expected ISO 8601 datetime')

        zones = payload.get('zones')
        if not isinstance(zones, dict) or not zones:
            return self._error(400, 'missing zones')
        if len(zones) > MAX_ZONES:
            return self._error(400, f'too many zones, max {MAX_ZONES}')

        zone_vals = []
        for name, temperature in zones.items():
            name = str(name).strip()
            if not name or len(name) > MAX_ZONE_NAME_LEN:
                return self._error(400, f'invalid zone name: {name!r}')
            if isinstance(temperature, bool) or \
                    not isinstance(temperature, (int, float)):
                return self._error(
                    400, f'invalid temperature for zone {name!r}, '
                         'expected a number')
            zone_vals.append((0, 0, {
                'zone_name': name,
                'temperature': float(temperature),
            }))

        request.env[model].sudo().create({
            'device_sn': device_sn,
            'collect_time': collect_dt,
            'zone_line_ids': zone_vals,
        })
        return request.make_json_response({'code': 200, 'message': '保存成功'})

    @staticmethod
    def _parse_collect_time(raw):
        """Parse an ISO 8601 datetime to a naive UTC datetime, else None."""
        if not raw or not isinstance(raw, str):
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    @staticmethod
    def _error(code, message):
        return request.make_json_response(
            {'code': code, 'message': message}, status=code)
