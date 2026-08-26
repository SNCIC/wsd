"""Thin PDA routes over the device service layer (equipment management).

The service owns the business rules (scan code in, board / task / repair
out); these routes only whitelist the action names and parameters, check
the barcode permission groups and normalize the answer into the PDA
{ok, message, data} envelope.
"""

from odoo import _, http
from odoo.http import request

# PDA whitelist: board / scan / task execution / repair report. Back-office
# actions (plans, templates, calibration, accept & record repair) stay on PC.
DEVICE_ACTION_PARAMS = {
    'today_board': ('location_id',),
    'locations': (),
    'resolve': ('code',),
    'task_start': ('kind', 'task_id'),
    'task_detail': ('kind', 'task_id'),
    'task_update_line': (
        'kind', 'line_id', 'measured_value', 'line_result', 'line_note'),
    'task_submit': ('kind', 'task_id'),
    'repair_create': ('code', 'fault_type', 'fault_level', 'description'),
}

INT_PARAMS = {'location_id', 'task_id', 'line_id'}


class SnPdaDeviceController(http.Controller):
    # 制造权限扁平化：只分 制造用户/制造管理员（PDA 场景即全体内部用户）
    GROUPS = ('mrp.group_mrp_user',)

    @http.route('/sn_wsd_barcode/pda/device/call', type='jsonrpc',
                auth='user')
    def device_call(self, action, **params):
        user = request.env.user
        if not user.has_group('base.group_system') and not any(
                user.has_group(group) for group in self.GROUPS):
            return {
                'ok': False,
                'message': _('No permission for this barcode operation.'),
            }
        allowed = DEVICE_ACTION_PARAMS.get(action)
        if allowed is None:
            return {'ok': False, 'message': _('Unknown action %s.', action)}
        kwargs = {}
        for key in allowed:
            value = params.get(key)
            if value is not None and key in INT_PARAMS:
                value = int(value)
            if value is not None:
                kwargs[key] = value
        try:
            result = getattr(request.env['sn.device.service'], action)(
                **kwargs)
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}
        if isinstance(result, (dict, list)):
            return {'ok': True, 'message': '', 'data': result}
        return {'ok': True, 'message': str(result)}
