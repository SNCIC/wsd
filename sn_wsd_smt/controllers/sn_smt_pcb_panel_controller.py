from odoo import http
from odoo.http import request


class SnSmtPcbPanelController(http.Controller):
    """SMT PCB Panel HTTP API (old-MES contract paths):
    - POST /api/v1/panels/add - F-001 panel creation.
    - POST /api/v1/panels/query - F-002 panel query.
    Plain JSON POST, no authentication; M_DATA_AUTH in the payload scopes
    the company.
    """

    def _body_or_error(self):
        try:
            data = request.get_json_data()
        except (ValueError, TypeError):
            data = None
        if not isinstance(data, dict):
            return None, request.make_json_response(
                {'code': 400, 'message': 'invalid json body', 'data': False},
                status=400)
        return dict(data), None

    def _call(self, service_method, params):
        try:
            result = service_method(params)
        except Exception as error:  # noqa: BLE001 - devices need a JSON body
            result = {'code': 500, 'message': f'Server error: {str(error)}'}
        status = result.get('code', 200) if isinstance(result, dict) else 200
        return request.make_json_response(result, status=status)

    def _service(self):
        return request.env['sn.smt.pcb.panel.api'].sudo().with_context(
            lang='zh_CN')

    @http.route('/api/v1/panels/add', type='http', auth='public',
                methods=['POST'], csrf=False)
    def api_panel_add(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        return self._call(self._service().api_panel_add, payload)

    @http.route('/api/v1/panels/query', type='http', auth='public',
                methods=['POST'], csrf=False)
    def api_panel_query(self, **kwargs):
        payload, error = self._body_or_error()
        if error:
            return error
        return self._call(self._service().api_panel_query, payload)
