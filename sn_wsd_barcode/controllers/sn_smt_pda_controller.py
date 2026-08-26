import re

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request


class SnSmtPdaController(http.Controller):
    # 制造权限扁平化：SMT PDA 门禁 = 制造用户
    GROUP_SMT = 'mrp.group_mrp_user'

    def _pda_group_check(self):
        if request.env.user.has_group('base.group_system'):
            return None
        if request.env.user.has_group(self.GROUP_SMT):
            return None
        return {'ok': False, 'message': _('No permission for this barcode operation.')}

    """SMT PDA jsonrpc 入口。路径与参数形状保持稳定，内部全部经由
    sn.smt.loading.service（制令单锚点）执行。"""

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def _get_service(self):
        return request.env['sn.smt.loading.service']

    def _get_workcenter(self, workcenter_id):
        workcenter = request.env['mrp.workcenter'].browse(workcenter_id).exists()
        if not workcenter:
            raise UserError(_('Work center not found.'))
        return workcenter

    def _get_online_mes_order(self, workcenter):
        # current pattern (kept in sync with sn.wsd.api.service._find_live_order):
        # online + station-mode orders filtered by line, matched by operation
        orders = request.env['sn.wsd.mes.order'].search([
            ('state', 'not in', ('cancelled', 'done')),
            ('x_online_date', '!=', False),
            ('x_manage_mode', '=', 'station'),
        ]).filtered(lambda o: (
            not workcenter.x_production_line_id
            or o.production_line_id == workcenter.x_production_line_id))
        operation = workcenter.x_operation_id
        for order in orders:
            if order.x_mes_route_id.operation_ids.filtered(
                    lambda r: r.operation_id == operation):
                return order.production_id, order
        raise UserError(_('No online manufacturing order was found for the selected work center.'))

    def _get_mes_order_by_production(self, production_id):
        production = request.env['mrp.production'].browse(production_id).exists()
        if not production:
            raise UserError(_('Manufacturing order not found.'))
        mes_order = production.x_mes_order_id
        if not mes_order:
            raise UserError(_('MES order not found.'))
        return production, mes_order

    # ------------------------------------------------------------------
    # Query endpoints
    # ------------------------------------------------------------------

    @http.route('/sn_wsd_barcode/smt/get_production_context', type='jsonrpc', auth='user')
    def get_production_context(self, workcenter_id, production_line_id=False):
        deny = self._pda_group_check()
        if deny:
            return deny
        workcenter = self._get_workcenter(workcenter_id)
        production, mes_order = self._get_online_mes_order(workcenter)
        if production_line_id:
            line = request.env['sn.mrp.production.line'].browse(production_line_id).exists()
            if line and mes_order.production_line_id != line:
                raise UserError(
                    _('The selected production line does not match the current online MES order.')
                )
        return {
            'production_id': production.id,
            'production_name': production.display_name,
            'mes_order_id': mes_order.id,
            'mes_order_name': mes_order.display_name,
            'product_default_code': mes_order.product_id.default_code,
            'product_side': mes_order.x_side,
            'smt_material_table_id': mes_order.x_smt_material_table_id.id,
            'smt_material_table_name': mes_order.x_smt_material_table_id.display_name,
            'production_line_id': mes_order.production_line_id.id,
            'production_line_name': mes_order.production_line_id.display_name,
        }

    @http.route('/sn_wsd_barcode/smt/get_material_table_status', type='jsonrpc', auth='user')
    def get_material_table_status(self, production_id):
        deny = self._pda_group_check()
        if deny:
            return deny
        production, mes_order = self._get_mes_order_by_production(production_id)
        status = self._get_service().get_material_status(mes_order)
        # 保持旧响应键（required_qty 等），供车间屏幕无感切换。
        rows = [{
            'device_seq': row['device_seq'],
            'table_no': row['table_no'],
            'loadpoint': row['loadpoint'],
            'channel': row['channel'],
            'item_code': row['item_code'],
            'required_qty': row['point_qty'],
            'loaded_material_lot_name': row['loaded_material_lot_name'],
            'loaded_material_available_qty': row['remaining_qty'],
            'loaded_feeder_name': row['loaded_feeder_name'],
            'load_status': row['load_status'],
            'replace_count': row['replace_count'],
            'is_skip': row['is_skip'],
        } for row in status['rows']]
        summary = status['summary']
        return {
            'production_id': production.id,
            'production_name': production.display_name,
            'mes_order_id': mes_order.id,
            'material_table_name': status['material_table_name'],
            'summary': {
                'required_qty': summary['required_qty'],
                'loaded_qty': summary['loaded_qty'],
                'unloaded_qty': summary['unloaded_qty'],
                'line_complete': summary['line_complete'],
                'active_rows': summary['required_qty'],
            },
            'rows': rows,
        }

    # ------------------------------------------------------------------
    # Action endpoints（委托服务层）
    # ------------------------------------------------------------------

    @http.route('/sn_wsd_barcode/smt/do_online_load', type='jsonrpc', auth='user')
    def do_online_load(
        self,
        production_id,
        workcenter_id,
        device_table_input,
        loadpoint_input,
        material_sn_input,
        feeder_sn_input=False,
    ):
        deny = self._pda_group_check()
        if deny:
            return deny
        _, mes_order = self._get_mes_order_by_production(production_id)
        workcenter = self._get_workcenter(workcenter_id)
        result = self._get_service().load_material(
            mes_order, workcenter, device_table_input, loadpoint_input,
            material_sn_input, feeder_sn=feeder_sn_input,
        )
        return {
            'ok': True,
            'message': result.get('message') or _('Online loading saved successfully.'),
            'production_id': production_id,
            'mes_order_id': mes_order.id,
            'online_material_id': result.get('online_material_id'),
            'material_lot_id': result.get('material_lot_id'),
            'feeder_id': result.get('feeder_id'),
        }

    @http.route('/sn_wsd_barcode/smt/do_offline_prepare', type='jsonrpc', auth='user')
    def do_offline_prepare(
        self,
        production_id,
        workcenter_id,
        device_table_input,
        loadpoint_input,
        material_sn_input,
        cart_sn_input=False,
        feeder_sn_input=False,
    ):
        deny = self._pda_group_check()
        if deny:
            return deny
        _, mes_order = self._get_mes_order_by_production(production_id)
        workcenter = self._get_workcenter(workcenter_id)
        cart = request.env['sn.smt.cart'].search([
            ('cart_sn', '=', cart_sn_input or ''),
            ('company_id', '=', mes_order.company_id.id),
        ], limit=1) if cart_sn_input else request.env['sn.smt.cart']
        if cart_sn_input and not cart:
            raise UserError(_('The cart SN does not exist.'))
        result = self._get_service().prepare_offline(
            mes_order, cart, feeder_sn_input, material_sn_input,
            slot_no=loadpoint_input or '',
        )
        return {
            'ok': True,
            'message': _('Offline preparation saved successfully.'),
            'production_id': production_id,
            'mes_order_id': mes_order.id,
            'cart_line_id': result.get('cart_line_id'),
        }

    @http.route('/sn_wsd_barcode/smt/do_offline_prepare_stage', type='jsonrpc', auth='user')
    def do_offline_prepare_stage(
        self,
        cart_sn_input,
        feeder_sn_input,
        material_sn_input,
        slot_no,
        production_id=False,
    ):
        """Offline cart preparation: order may not be online yet, the cart
        carries the line until mount time."""
        deny = self._pda_group_check()
        if deny:
            return deny
        cart = request.env['sn.smt.cart'].search([
            ('cart_sn', '=', cart_sn_input or ''),
            ('status', '!=', 'disabled'),
        ], limit=1)
        if not cart:
            return {'ok': False, 'message': _('The cart SN does not exist.')}
        mes_order = False
        if production_id:
            _production, mes_order = self._get_mes_order_by_production(production_id)
        try:
            result = self._get_service().prepare_offline_stage(
                cart, feeder_sn_input, material_sn_input, slot_no,
                mes_order=mes_order)
        except UserError as error:
            return {'ok': False, 'message': str(error)}
        return {
            'ok': True,
            'message': _('Prepared on cart %s (slot %s).', cart.cart_sn, slot_no),
            'cart_line_id': result.get('cart_line_id'),
        }

    @http.route('/sn_wsd_barcode/smt/do_cart_load', type='jsonrpc', auth='user')
    def do_cart_load(self, production_id, workcenter_id, device_table_input, cart_sn_input):
        deny = self._pda_group_check()
        if deny:
            return deny
        _, mes_order = self._get_mes_order_by_production(production_id)
        workcenter = self._get_workcenter(workcenter_id)
        cart = request.env['sn.smt.cart'].search([
            ('cart_sn', '=', cart_sn_input or ''),
            ('company_id', '=', mes_order.company_id.id),
        ], limit=1)
        if not cart:
            raise UserError(_('The cart SN does not exist.'))
        result = self._get_service().load_cart(
            mes_order, workcenter, device_table_input, cart,
        )
        loaded = result.get('loaded_slots') or []
        skipped = result.get('skipped_slots') or []
        if skipped:
            message = _(
                'Cart loading: %(loaded)d station(s) loaded, %(skipped)d '
                'skipped (slots: %(slots)s -- no matching online position '
                'or already loaded).',
                loaded=len(loaded), skipped=len(skipped),
                slots=', '.join(skipped))
        else:
            message = _(
                'Cart loading: %(loaded)d station(s) loaded, all matched.',
                loaded=len(loaded))
        return {
            'ok': True,
            'message': message,
            'loaded_slots': loaded,
            'skipped_slots': skipped,
            'production_id': production_id,
            'mes_order_id': mes_order.id,
        }

    @http.route('/sn_wsd_barcode/smt/do_changeover', type='jsonrpc', auth='user')
    def do_changeover(self, production_id, target_production_id, workcenter_id):
        deny = self._pda_group_check()
        if deny:
            return deny
        _, source_mes_order = self._get_mes_order_by_production(production_id)
        _, target_mes_order = self._get_mes_order_by_production(target_production_id)
        workcenter = self._get_workcenter(workcenter_id)
        result = self._get_service().changeover(source_mes_order, target_mes_order, workcenter)
        return {
            'ok': True,
            'message': result.get('message') or _('Changeover completed.'),
            'production_id': target_production_id,
            'mes_order_id': target_mes_order.id,
        }

    @http.route('/sn_wsd_barcode/smt/do_continue', type='jsonrpc', auth='user')
    def do_continue(
        self,
        production_id,
        workcenter_id,
        device_table_input,
        loadpoint_input,
        old_material_sn_input,
        new_material_sn_input,
        new_feeder_sn_input=False,
        change_type='continue',
    ):
        deny = self._pda_group_check()
        if deny:
            return deny
        _, mes_order = self._get_mes_order_by_production(production_id)
        workcenter = self._get_workcenter(workcenter_id)
        old_lot = request.env['stock.lot'].search([
            ('name', '=', old_material_sn_input or ''),
        ], limit=1)
        if old_lot:
            position = request.env['sn.smt.online.material'].search([
                ('mes_order_id', '=', mes_order.id),
                ('loaded_material_lot_id', '=', old_lot.id),
                ('is_load', '=', 'Y'),
            ], limit=1)
            if position:
                device_table_input = device_table_input or f'{position.device_seq}.{position.table_no}'
                loadpoint_input = loadpoint_input or position.loadpoint
        result = self._get_service().change_material(
            mes_order, workcenter, device_table_input, loadpoint_input,
            new_material_sn_input, new_feeder_sn=new_feeder_sn_input,
            change_type=change_type or 'continue',
        )
        return {
            'ok': True,
            'message': result.get('message') or _('Material change or continuation completed.'),
            'production_id': production_id,
            'mes_order_id': mes_order.id,
        }

    @http.route('/sn_wsd_barcode/smt/do_unload', type='jsonrpc', auth='user')
    def do_unload(
        self,
        production_id,
        workcenter_id,
        unload_scope,
        device_table_input=False,
        loadpoint_input=False,
        cart_input=False,
        material_sn_input=False,
    ):
        deny = self._pda_group_check()
        if deny:
            return deny
        _, mes_order = self._get_mes_order_by_production(production_id)
        cart = request.env['sn.smt.cart']
        if cart_input:
            cart = request.env['sn.smt.cart'].search([
                ('cart_sn', '=', cart_input),
                ('company_id', '=', mes_order.company_id.id),
            ], limit=1)
            if not cart:
                raise UserError(_('The cart SN does not exist.'))
        result = self._get_service().unload(
            mes_order, scope=unload_scope or 'station',
            device_table=device_table_input or False,
            loadpoint=loadpoint_input or False,
            material_sn=material_sn_input or False,
            cart=cart,
        )
        return {
            'ok': True,
            'message': _('Unload completed.'),
            'production_id': production_id,
            'mes_order_id': mes_order.id,
            'unloaded_qty': result.get('unloaded_qty', 0),
        }

    # ------------------------------------------------------------------
    # Unified barcode entry
    # ------------------------------------------------------------------

    @http.route('/sn_wsd_barcode/smt/process_smt_scan', type='jsonrpc', auth='user')
    def process_smt_scan(self, station_id, barcode, operation):
        deny = self._pda_group_check()
        if deny:
            return deny
        workcenter = self._get_workcenter(station_id)
        try:
            production, mes_order = self._get_online_mes_order(workcenter)
        except UserError:
            return {
                'ok': False,
                'message': _(
                    'No online manufacturing order was found for the selected workshop and production line.'
                ),
            }
        if not mes_order:
            return {
                'ok': False,
                'message': _('No online MES order was found for the selected workshop and production line.'),
            }
        service = self._get_service()

        def extract(key):
            pattern = rf'(?:^|\|){re.escape(key)}=([^|]+)'
            match = re.search(pattern, barcode or '', re.IGNORECASE)
            return match.group(1).strip() if match else ''

        try:
            if operation in ('feeder_unload', 'online_load'):
                device_table_input = extract('DEV')
                loadpoint_input = extract('LP')
                material_sn_input = extract('MAT')
                feeder_sn_input = extract('FD')
                if not device_table_input or not loadpoint_input:
                    return {
                        'ok': False,
                        'message': _('Load format: DEV=N.T|LP=xxx|MAT=xxx|FD=xxx'),
                        'barcode': barcode,
                    }
                if not material_sn_input:
                    return {
                        'ok': False,
                        'message': _('Load barcode is missing the MAT field.'),
                        'barcode': barcode,
                    }
                service.load_material(
                    mes_order, workcenter, device_table_input, loadpoint_input,
                    material_sn_input, feeder_sn=feeder_sn_input,
                )
                return {
                    'ok': True,
                    'message': _('SMT load completed: %(device)s %(loadpoint)s %(material)s') % {
                        'device': device_table_input,
                        'loadpoint': loadpoint_input,
                        'material': material_sn_input,
                    },
                    'operation': 'online_load',
                    'production_id': production.id,
                    'mes_order_id': mes_order.id,
                    'production_name': production.display_name,
                }

            if operation == 'offline_prepare':
                device_table_input = extract('DEV')
                loadpoint_input = extract('LP')
                material_sn_input = extract('MAT')
                feeder_sn_input = extract('FD')
                cart_sn_input = extract('CART')
                if not device_table_input or not loadpoint_input or not material_sn_input:
                    return {
                        'ok': False,
                        'message': _('Offline prepare format: DEV=N.T|LP=xxx|MAT=xxx|FD=xxx|CART=xxx'),
                        'barcode': barcode,
                    }
                cart = request.env['sn.smt.cart']
                if cart_sn_input:
                    cart = request.env['sn.smt.cart'].search([
                        ('cart_sn', '=', cart_sn_input),
                        ('company_id', '=', mes_order.company_id.id),
                    ], limit=1)
                    if not cart:
                        raise UserError(_('The cart SN does not exist.'))
                service.prepare_offline(
                    mes_order, cart, feeder_sn_input, material_sn_input,
                    slot_no=loadpoint_input,
                )
                return {
                    'ok': True,
                    'message': _('SMT offline preparation completed: %(device)s %(loadpoint)s %(material)s') % {
                        'device': device_table_input,
                        'loadpoint': loadpoint_input,
                        'material': material_sn_input,
                    },
                    'operation': 'offline_prepare',
                    'production_id': production.id,
                    'mes_order_id': mes_order.id,
                    'production_name': production.display_name,
                }

            if operation == 'cart_load':
                device_table_input = extract('DEV')
                cart_sn_input = extract('CART')
                if not device_table_input or not cart_sn_input:
                    return {
                        'ok': False,
                        'message': _('Cart load format: DEV=N.T|CART=xxx'),
                        'barcode': barcode,
                    }
                cart = request.env['sn.smt.cart'].search([
                    ('cart_sn', '=', cart_sn_input),
                    ('company_id', '=', mes_order.company_id.id),
                ], limit=1)
                if not cart:
                    raise UserError(_('The cart SN does not exist.'))
                service.load_cart(mes_order, workcenter, device_table_input, cart)
                return {
                    'ok': True,
                    'message': _('SMT cart load completed: %(device)s %(cart)s') % {
                        'device': device_table_input,
                        'cart': cart_sn_input,
                    },
                    'operation': 'cart_load',
                    'production_id': production.id,
                    'mes_order_id': mes_order.id,
                    'production_name': production.display_name,
                }

            if operation == 'table_unload':
                material_sn_input = extract('MAT')
                if not material_sn_input:
                    return {
                        'ok': False,
                        'message': _('Unload format: MAT=xxx'),
                        'barcode': barcode,
                    }
                service.unload(mes_order, scope='material', material_sn=material_sn_input)
                return {
                    'ok': True,
                    'message': _('SMT unload completed: %(material)s') % {
                        'material': material_sn_input,
                    },
                    'operation': 'unload',
                    'production_id': production.id,
                    'mes_order_id': mes_order.id,
                    'production_name': production.display_name,
                }

            if operation == 'material_refill':
                old_material_sn = extract('OLD_MAT')
                new_material_sn = extract('NEW_MAT')
                if not old_material_sn or not new_material_sn:
                    return {
                        'ok': False,
                        'message': _('Refill format: OLD_MAT=old material SN|NEW_MAT=new material SN'),
                        'barcode': barcode,
                    }
                if old_material_sn == new_material_sn:
                    return {
                        'ok': False,
                        'message': _('Old and new material SN cannot be the same.'),
                        'barcode': barcode,
                    }
                old_lot = request.env['stock.lot'].search([
                    ('name', '=', old_material_sn),
                ], limit=1)
                position = request.env['sn.smt.online.material'].search([
                    ('mes_order_id', '=', mes_order.id),
                    ('loaded_material_lot_id', '=', old_lot.id),
                    ('is_load', '=', 'Y'),
                ], limit=1) if old_lot else request.env['sn.smt.online.material']
                if not position:
                    return {
                        'ok': False,
                        'message': _('The old material SN is not loaded online.'),
                        'barcode': barcode,
                    }
                service.change_material(
                    mes_order, workcenter,
                    f'{position.device_seq}.{position.table_no}',
                    position.loadpoint, new_material_sn,
                    change_type='change',
                )
                return {
                    'ok': True,
                    'message': _('SMT refill completed: %(old)s -> %(new)s') % {
                        'old': old_material_sn,
                        'new': new_material_sn,
                    },
                    'operation': 'change',
                    'production_id': production.id,
                    'mes_order_id': mes_order.id,
                    'production_name': production.display_name,
                }
        except UserError as error:
            return {'ok': False, 'message': str(error)}

        return {
            'ok': False,
            'message': _('Unknown SMT operation: %(operation)s', operation=operation),
        }

    # ------------------------------------------------------------------
    # 投料（插件/装配关键物料，无料站表）——整机工组
    # ------------------------------------------------------------------

    def _shop_group_check(self):
        if request.env.user.has_group('base.group_system'):
            return None
        if request.env.user.has_group('mrp.group_mrp_user'):
            return None
        return {'ok': False, 'message': _('No permission for this barcode operation.')}

    def _find_mes_order_by_barcode(self, barcode):
        """扫制令单条码：优先按制令单名（WH/MO/xxxx-N）查，回退按
        mrp.production 名（WH/MO/xxxx）取其制令单。注意不要用 `_` 做
        解包占位——本文件里 `_` 是翻译函数。"""
        name = (barcode or '').strip()
        mes_order = request.env['sn.wsd.mes.order'].search([
            ('name', '=', name),
            ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not mes_order:
            production = request.env['mrp.production'].search([
                ('name', '=', name),
                ('company_id', 'in', request.env.companies.ids),
            ], limit=1)
            mes_order = production.x_mes_order_id
        if not mes_order:
            raise UserError(_('No MES order was found for %s.', name))
        if mes_order.state in ('cancelled', 'done'):
            raise UserError(_('The MES order %s is closed.', mes_order.display_name))
        return mes_order.production_id, mes_order

    @http.route('/sn_wsd_barcode/smt/do_drawing_open', type='jsonrpc', auth='user')
    def do_drawing_open(self, barcode):
        deny = self._shop_group_check()
        if deny:
            return deny
        production, mes_order = self._find_mes_order_by_barcode(barcode)
        status = self._get_service().drawing_status(mes_order)
        if not status['rows']:
            return {
                'ok': False,
                'message': _(
                    'Order %s has no critical material list rows. Loading '
                    'control is not configured for it.', mes_order.display_name),
            }
        status['ok'] = True
        status['production_id'] = production.id
        return status

    @http.route('/sn_wsd_barcode/smt/do_drawing_scan', type='jsonrpc', auth='user')
    def do_drawing_scan(self, production_id, barcode, workcenter_id=False):
        deny = self._shop_group_check()
        if deny:
            return deny
        _production, mes_order = self._get_mes_order_by_production(production_id)
        workcenter = self._get_workcenter(workcenter_id) if workcenter_id else False
        try:
            result = self._get_service().load_drawing_barcode(
                mes_order, barcode, workcenter=workcenter)
        except UserError as error:
            status = self._get_service().drawing_status(mes_order)
            status['ok'] = False
            status['message'] = str(error)
            return status
        status = self._get_service().drawing_status(mes_order)
        status['ok'] = True
        status['message'] = result['message']
        return status

    @http.route('/sn_wsd_barcode/smt/do_drawing_unload_all', type='jsonrpc', auth='user')
    def do_drawing_unload_all(self, production_id):
        deny = self._shop_group_check()
        if deny:
            return deny
        _production, mes_order = self._get_mes_order_by_production(production_id)
        result = self._get_service().unload_drawing_all(mes_order)
        status = self._get_service().drawing_status(mes_order)
        status['ok'] = True
        status['message'] = result['message']
        return status

    @http.route('/sn_wsd_barcode/smt/do_drawing_context', type='jsonrpc', auth='user')
    def do_drawing_context(self, workcenter_id):
        """投料定位：工位 → 本产线在线制令单 → 关键物料清单状态
        （不扫制令单条码，与 SMT 车间屏定位方式一致）。"""
        deny = self._shop_group_check()
        if deny:
            return deny
        workcenter = self._get_workcenter(workcenter_id)
        try:
            production, mes_order = self._get_online_mes_order(workcenter)
        except UserError as error:
            return {'ok': False, 'message': str(error)}
        status = self._get_service().drawing_status(mes_order)
        status['ok'] = True
        status['production_id'] = production.id
        return status
