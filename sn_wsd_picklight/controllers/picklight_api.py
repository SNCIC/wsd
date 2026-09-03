import json
from datetime import datetime

from odoo import fields, http
from odoo.http import request


class PicklightApi(http.Controller):

    def _payload(self):
        try:
            payload = json.loads(request.httprequest.get_data() or b'{}')
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _config(self):
        config = request.env['sn.wsd.picklight.config'].sudo().get_active(
            request.env.company)
        token = request.httprequest.headers.get('X-API-Token')
        if config and config.api_token and token != config.api_token:
            return None
        return config

    def _json(self, body, status=200):
        return request.make_json_response(body, status=status)

    def _event(self, event_type, payload, values):
        config = self._config()
        if not config:
            return self._json({'Result': 0, 'Message': 'Unauthorized'}, 401)
        values.update({
            'name': '%s-%s' % (event_type, fields.Datetime.now()),
            'company_id': config.company_id.id,
            'event_type': event_type,
            'event_time': values.get('event_time') or fields.Datetime.now(),
            'payload': payload,
        })
        location = request.env['sn.wsd.picklight.location'].sudo().search([
            ('company_id', '=', config.company_id.id),
            ('code', '=', values.get('location_code')),
        ], limit=1)
        if location:
            values['stock_location_id'] = location.stock_location_id.id
            values['shelf_code'] = location.shelf_id.code
        request.env['sn.wsd.picklight.event'].sudo().create(values)
        return self._json({'Result': 1, 'Message': 'Command received.'})

    def _request_config(self):
        config = self._config()
        if not config:
            return None
        return config

    @http.route('/api/picklight/health', type='http', auth='none', methods=['POST'], csrf=False)
    def health(self, **kwargs):
        return self._json({'Result': 1, 'Message': 'Picklight callback service is available.'})

    @http.route('/api/picklight/status-changed', type='http', auth='none', methods=['POST'], csrf=False)
    def status_changed(self, **kwargs):
        payload = self._payload()
        if payload is None:
            return self._json({'Result': 0, 'Message': 'Invalid JSON body.'}, 400)
        return self._event('status_changed', payload, {
            'location_code': payload.get('LocationId'),
            'state': payload.get('State'),
            'light_color': payload.get('LightColor'),
            'event_time': self._parse_time(payload.get('time')),
        })

    @http.route('/api/picklight/pressed', type='http', auth='none', methods=['POST'], csrf=False)
    def pressed(self, **kwargs):
        payload = self._payload()
        if payload is None:
            return self._json({'Result': 0, 'Message': 'Invalid JSON body.'}, 400)
        return self._event('pressed', payload, {
            'location_code': payload.get('LocationId'),
            'light_color': payload.get('LightColor'),
            'quantity': payload.get('Quantity'),
            'batch_code': payload.get('BatchCode'),
        })

    @http.route('/api/picklight/scan-changed', type='http', auth='none', methods=['POST'], csrf=False)
    def scan_changed(self, **kwargs):
        payload = self._payload()
        if payload is None:
            return self._json({'Result': 0, 'Message': 'Invalid JSON body.'}, 400)
        return self._event('scan_changed', payload, {
            'location_code': payload.get('LocationId'),
            'barcode': payload.get('BarCode'),
        })

    @http.route('/api/picklight/self-checking', type='http', auth='none', methods=['POST'], csrf=False)
    def self_checking(self, **kwargs):
        payload = self._payload()
        if payload is None:
            return self._json({'Result': 0, 'Message': 'Invalid JSON body.'}, 400)
        return self._event('self_checking', payload, {
            'shelf_code': payload.get('ShelfCode'),
        })

    @staticmethod
    def _parse_time(value):
        if not value:
            return fields.Datetime.now()
        try:
            return datetime.fromisoformat(str(value).replace(' ', 'T'))
        except ValueError:
            return fields.Datetime.now()
