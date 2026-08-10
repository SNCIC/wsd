from odoo import http
from odoo.http import request


class SnSmtPcbPanelController(http.Controller):
    """
    SMT PCB Panel HTTP API Controller

    Provides REST API endpoints for external MES systems:
    - POST /api/smt/panel/add - F-001 panel creation.
    - POST /api/smt/panel/query - F-002 panel query.
    - GET /api/smt/panel/<id> - Panel detail.
    - DELETE /api/smt/panel/<id> - Panel deletion.
    """

    @http.route('/api/smt/panel/add', type='json', auth='user', methods=['POST'], csrf=False)
    def api_panel_add(self, **kwargs):
        """
        F-001 panel creation.

        Request example:
        {
            "productNo": "MO20260525123589",
            "quantity": 4,
            "pcbItemSn": "3111001398",
            "bindings": [
                {"boardNo": "1", "proSn": "W23350859A01S012624553250"},
                {"boardNo": "2", "proSn": "W23350859A01S012624553252"},
                {"boardNo": "3", "proSn": "W23350859A01S012624553253"},
                {"boardNo": "4", "proSn": "W23350859A01S012624553251"}
            ]
        }

        Success response:
        {"code": 200, "message": "\u4fdd\u5b58\u6210\u529f"}

        Error response:
        {"code": 400, "message": "\u7b2c2\u6761\u8bb0\u5f55\uff1a\u4ea7\u54c1SN[W23350859A01S012624553252]\u4e0d\u5b58\u5728"}
        """
        try:
            params = request.jsonrequest
            api_service = request.env['sn.smt.pcb.panel.api']
            result = api_service.sudo().api_panel_add(params)
            return result
        except Exception as e:
            return {'code': 500, 'message': f'Server error: {str(e)}'}

    @http.route('/api/smt/panel/query', type='json', auth='user', methods=['POST'], csrf=False)
    def api_panel_query(self, **kwargs):
        """
        F-002 panel query.

        Request example:
        // Query by manufacturing batch number.
        {"productNo": "BATCH20260525123589"}

        // Query by board internal serial number.
        {"proSn": "W23350859A01S012624553252"}

        Success response:
        {
            "code": 200,
            "message": "Query successful.",
            "data": {
                "panels": [...],
                "total": 1
            }
        }
        """
        try:
            params = request.jsonrequest
            api_service = request.env['sn.smt.pcb.panel.api']
            result = api_service.sudo().api_panel_query(params)
            return result
        except Exception as e:
            return {'code': 500, 'message': f'Server error: {str(e)}'}

    @http.route('/api/smt/panel/<int:panel_id>', type='json', auth='user', methods=['GET'], csrf=False)
    def api_panel_detail(self, panel_id, **kwargs):
        """
        Get panel details.

        GET /api/smt/panel/<panel_id>

        Success response:
        {
            "code": 200,
            "message": "Query successful.",
            "data": {...}
        }
        """
        try:
            api_service = request.env['sn.smt.pcb.panel.api']
            result = api_service.sudo().api_panel_detail(panel_id)
            return result
        except Exception as e:
            return {'code': 500, 'message': f'Server error: {str(e)}'}

    @http.route('/api/smt/panel/<int:panel_id>', type='json', auth='user', methods=['DELETE'], csrf=False)
    def api_panel_delete(self, panel_id, **kwargs):
        """
        Delete a panel record.

        DELETE /api/smt/panel/<panel_id>

        Success response:
        {"code": 200, "message": "Deleted successfully."}
        """
        try:
            api_service = request.env['sn.smt.pcb.panel.api']
            result = api_service.sudo().api_panel_delete(panel_id)
            return result
        except Exception as e:
            return {'code': 500, 'message': f'Server error: {str(e)}'}
