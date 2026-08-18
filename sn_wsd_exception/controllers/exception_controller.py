from odoo import http
from odoo.http import request


class SnWsdExceptionController(http.Controller):

    def _record_data(self, record):
        return {
            'id': record.id,
            'name': record.name,
            'state': record.state,
            'category': record.category,
            'exception_type_id': record.exception_type_id.id,
            'exception_type_name': record.exception_type_id.display_name,
        }

    @http.route('/sn_wsd_exception/get_exception_types', type='jsonrpc', auth='user')
    def get_exception_types(self):
        exception_types = request.env['sn.wsd.exception.type'].search([('active', '=', True)])
        return [{
            'id': exception_type.id,
            'name': exception_type.display_name,
            'code': exception_type.code,
            'category': exception_type.category,
        } for exception_type in exception_types]

    @http.route('/sn_wsd_exception/create_exception', type='jsonrpc', auth='user')
    def create_exception(self, exception_type_id, description, context_data=None):
        context_data = context_data or {}
        vals = {
            'exception_type_id': int(exception_type_id),
            'description': description,
        }
        mapping = {
            'production_id': 'production_id',
            'route_operation_id': 'route_operation_id',
            'workcenter_id': 'workcenter_id',
            'route_step_id': 'route_step_id',
            'equipment_id': 'equipment_id',
            'internal_serial_id': 'internal_serial_id',
            'serial_lot_id': 'serial_lot_id',
            'material_product_id': 'material_product_id',
            'responsible_user_id': 'responsible_user_id',
            'verifier_user_id': 'verifier_user_id',
            'occurred_at': 'occurred_at',
        }
        for source_key, target_key in mapping.items():
            value = context_data.get(source_key)
            if value:
                vals[target_key] = value
        record = request.env['sn.wsd.exception.record'].create(vals)
        return self._record_data(record)
