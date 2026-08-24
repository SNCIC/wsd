"""Thin PDA routes over the tooling / consumable service layers.

The services own the business rules (scan SN in, translated message out);
these routes only whitelist the action names, check the barcode permission
groups and normalize the answer into the PDA {ok, message} envelope.
"""

from odoo import _, http
from odoo.http import request

# PDA whitelist: floor operations only. Admin-ish actions (disable /
# enable / info-lookup) stay on the back office, never on the scanner.
TOOLING_ACTIONS = {
    'issue', 'return_', 'online', 'offline',
    'maintain_start', 'maintain_done', 'repair_start', 'repair_done',
}
CONSUMABLE_ACTIONS = {
    'issue', 'return_', 'thaw_start', 'thaw_end',
    'stir_start', 'stir_end', 'load', 'unload', 'exhaust',
}

# actions that carry one extra free-text parameter besides the SN
EXTRA_PARAMS = {
    'repair_start': 'fault',
}


class SnPdaEquipmentController(http.Controller):
    GROUPS = (
        'sn_wsd_mrp.group_mes_shop',
        'sn_wsd_mrp.group_mes_smt_operator',
    )

    def _pda_call(self, service_model, allowed, action, params):
        user = request.env.user
        if user.has_group('base.group_system'):
            pass
        elif not user.has_group(self.GROUPS[0]) and not user.has_group(self.GROUPS[1]):
            return {'ok': False, 'message': _('No permission for this barcode operation.')}
        if action not in allowed:
            return {'ok': False, 'message': _('Unknown action %s.', action)}
        kwargs = {'sn': (params.get('sn') or '').strip()}
        extra = EXTRA_PARAMS.get(action)
        if extra:
            kwargs[extra] = params.get(extra) or ''
        try:
            result = getattr(request.env[service_model], action)(**kwargs)
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}
        if isinstance(result, dict):
            return {'ok': True, 'message': '', 'data': result}
        return {'ok': True, 'message': str(result)}

    @http.route('/sn_wsd_barcode/pda/tooling/call', type='jsonrpc', auth='user')
    def tooling_call(self, action, **params):
        return self._pda_call('sn.tooling.service', TOOLING_ACTIONS, action, params)

    @http.route('/sn_wsd_barcode/pda/consumable/call', type='jsonrpc', auth='user')
    def consumable_call(self, action, **params):
        return self._pda_call('sn.consumable.service', CONSUMABLE_ACTIONS, action, params)
