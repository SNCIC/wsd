"""Thin PDA routes over the tooling / consumable service layers.

The services own the business rules (scan SN in, translated message out);
these routes only whitelist the action names, check the barcode permission
groups and normalize the answer into the PDA {ok, message} envelope.
"""

from odoo import _, http
from odoo.exceptions import ValidationError
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
    # 制造权限扁平化：只分 制造用户/制造管理员（PDA 场景即全体内部用户）
    GROUPS = ('mrp.group_mrp_user',)

    def _pda_call(self, service_model, allowed, action, params):
        user = request.env.user
        if not user.has_group('base.group_system') and not any(
                user.has_group(group) for group in self.GROUPS):
            return {'ok': False, 'message': _('No permission for this barcode operation.')}
        if action not in allowed:
            return {'ok': False, 'message': _('Unknown action %s.', action)}
        kwargs = {'sn': (params.get('sn') or '').strip()}
        extra = EXTRA_PARAMS.get(action)
        if extra:
            kwargs[extra] = params.get(extra) or ''
        if params.get('mes_order') is not None:
            kwargs['mes_order'] = params.get('mes_order')
        try:
            result = getattr(request.env[service_model], action)(**kwargs)
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}
        if isinstance(result, dict):
            return {'ok': True, 'message': '', 'data': result}
        return {'ok': True, 'message': str(result)}

    @http.route('/sn_wsd_barcode/pda/tooling/call', type='jsonrpc', auth='user')
    def tooling_call(self, action, **params):
        result = self._pda_call('sn.tooling.service', TOOLING_ACTIONS, action, params)
        # 上线/下线联动关键物料清单行：设备页签的 online/offline 与投料
        # 屏扫码等效——同模板的清单行 is_load 跟随点亮/熄灭
        if action in ('online', 'offline') and result.get('ok'):
            workcenter = self.env['mrp.workcenter'].browse(
                int(params.get('workcenter_id') or 0)).exists()
            try:
                order = self._live_mes_order(workcenter)
            except ValidationError:
                order = self.env['sn.wsd.mes.order']
            if order:
                tooling = self.env['sn.tooling'].search(
                    [('sn', '=', (params.get('sn') or '').strip())], limit=1)
                if tooling and tooling.template_id:
                    self._sync_drawing_rows(
                        order, 'tooling', tooling.template_id, tooling,
                        loaded=(action == 'online'))
        return result

    @http.route('/sn_wsd_barcode/pda/consumable/call', type='jsonrpc', auth='user')
    def consumable_call(self, action, **params):
        # Loading a consumable binds it to the live MES order of the
        # work center the operator is standing at; the scanner screen
        # always sends that work center along.
        order = self.env['sn.wsd.mes.order']
        if action == 'load':
            workcenter = self.env['mrp.workcenter'].browse(
                int(params.get('workcenter_id') or 0)).exists()
            order = self._live_mes_order(workcenter)
            params['mes_order'] = order.id
        result = self._pda_call('sn.consumable.service', CONSUMABLE_ACTIONS, action, params)
        # 上线/下线/用尽联动关键物料清单行（同制具口径）
        if action in ('load', 'unload', 'exhaust') and result.get('ok'):
            if not order:
                workcenter = self.env['mrp.workcenter'].browse(
                    int(params.get('workcenter_id') or 0)).exists()
                try:
                    order = self._live_mes_order(workcenter)
                except ValidationError:
                    order = self.env['sn.wsd.mes.order']
            if order:
                info = self.env['sn.consumable.info'].search(
                    [('sn', '=', (params.get('sn') or '').strip())], limit=1)
                if info and info.template_id:
                    self._sync_drawing_rows(
                        order, 'consumable', info.template_id, info,
                        loaded=(action == 'load'))
        return result

    def _sync_drawing_rows(self, order, material_type, template, individual, loaded):
        """Flip the order's critical-material rows of this template to match
        the individual's online state (equipment tab == loading screen).
        material_ref is a Reference field: compare against the record -- its
        Python value is a browse record, never the 'model,id' string."""
        rows = order.x_smt_online_material_ids.filtered(
            lambda l: l.source == 'drawing_list'
            and l.drawing_material_type == material_type
            and l.drawing_material_line_id.material_ref == template)
        vals = {'is_load': 'Y' if loaded else 'N'}
        if material_type == 'tooling':
            vals['tooling_id'] = individual.id if loaded else False
        else:
            vals['consumable_info_id'] = individual.id if loaded else False
        rows.write(vals)

    def _live_mes_order(self, workcenter):
        """The online station-mode MES order running through this work center."""
        if not workcenter or not workcenter.x_operation_id:
            raise ValidationError(_(
                'Pick a work center with an operation before loading a '
                'consumable.'))
        orders = self.env['sn.wsd.mes.order'].search([
            ('state', 'not in', ('cancelled', 'done')),
            ('x_online_date', '!=', False),
            ('x_manage_mode', '=', 'station'),
        ]).filtered(lambda o: (
            not workcenter.x_production_line_id
            or o.production_line_id == workcenter.x_production_line_id))
        for order in orders:
            if order.x_mes_route_id.operation_ids.filtered(
                    lambda r: r.operation_id == workcenter.x_operation_id):
                return order
        raise ValidationError(_(
            'No online MES order runs through work center %s.',
            workcenter.code or workcenter.name))
