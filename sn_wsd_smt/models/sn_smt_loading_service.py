import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

DEVICE_TABLE_PATTERN = re.compile(r'^\s*(\d+)\.([A-Za-z0-9_-]+)\s*$')


class SnSmtLoadingService(models.AbstractModel):
    """SMT 上料六动作服务层：直接上料 / 备料 / 料车上料 / 换续料 / 下料 / 转机继承。
    供 PDA 接口（REST + jsonrpc）调用；每次操作同时写在线料表状态与物料日志。"""
    _name = 'sn.smt.loading.service'
    _description = 'SMT Loading Service'
    _inherit = 'sn.smt.operation.mixin'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _parse_device_table(self, device_table):
        match = DEVICE_TABLE_PATTERN.match(device_table or '')
        if not match:
            raise UserError(_('The Device.TABLE input format is invalid.'))
        return int(match.group(1)), match.group(2)

    @api.model
    def _is_feeder_control_enabled(self, mes_order):
        line = mes_order.production_line_id
        return bool(line and line.x_smt_is_feeder_control)

    @api.model
    def _find_position(self, mes_order, device_seq, table_no, loadpoint, require_unloaded=True):
        candidates = mes_order.x_smt_online_material_ids.filtered(
            lambda line: line.device_seq == device_seq and line.table_no == table_no
        )
        if not candidates:
            raise UserError(_('The current device table does not require online loading.'))
        target = candidates.filtered(lambda line: line.loadpoint == loadpoint)[:1]
        if not target:
            raise UserError(_('The current loadpoint does not require online loading.'))
        if target.is_skip == 'Y':
            raise UserError(_('The current loadpoint is skipped and does not require online loading.'))
        if require_unloaded and target.is_load == 'Y':
            raise UserError(_('The current loadpoint is already loaded online.'))
        return target

    @api.model
    def _resolve_material_lot(self, mes_order, material_sn):
        """物料SN 只查找、不创建：料均由仓库发放，批次先于扫码存在。"""
        material_lot = self.env['stock.lot'].search([
            ('name', '=', (material_sn or '').strip()),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', mes_order.company_id.id),
        ], limit=1)
        if not material_lot:
            raise UserError(_('No material lot was found for the material SN.'))
        return material_lot

    @api.model
    def _resolve_feeder(self, mes_order, online_material, feeder_sn):
        if online_material.is_tray == 'Y':
            return self.env['sn.smt.feeder']
        feeder_sn = (feeder_sn or '').strip()
        if not feeder_sn:
            if self._is_feeder_control_enabled(mes_order):
                raise UserError(_('Feeder control is enabled on the production line: scan the feeder SN first.'))
            return self.env['sn.smt.feeder']
        feeder = self.env['sn.smt.feeder'].search([
            ('feeder_sn', '=', feeder_sn),
            ('company_id', '=', mes_order.company_id.id),
        ], limit=1)
        if not feeder:
            raise UserError(_('The feeder SN does not exist.'))
        if feeder.status not in ('normal', 'in_use'):
            raise UserError(_('The feeder status is invalid.'))
        if not feeder.maintenance_ok:
            raise UserError(_('The feeder is not available for use because maintenance is not valid.'))
        if online_material.chanel_sn and feeder.channel_ids \
                and online_material.chanel_sn not in feeder.channel_ids.mapped('channel_sn'):
            raise UserError(_('The feeder channel does not match the SMT position channel.'))
        if online_material.feeder_spec and feeder.feeder_spec \
                and feeder.feeder_spec != online_material.feeder_spec:
            raise UserError(_('The feeder specification does not match the SMT position requirement.'))
        return feeder

    @api.model
    def _log(self, mes_order, online_material, operation_type, material_lot=False,
             old_material_lot=False, old_lot_qty=0.0, feeder=False, cart=False,
             workcenter=False, qty_before=False, qty_after=False, note=False):
        return self.env['sn.smt.material.log'].create({
            'mes_order_id': mes_order.id,
            'online_material_id': online_material.id if online_material else False,
            'workcenter_id': workcenter.id if workcenter else False,
            'operation_type': operation_type,
            'material_lot_id': material_lot.id if material_lot else False,
            'old_material_lot_id': old_material_lot.id if old_material_lot else False,
            'old_lot_qty': old_lot_qty,
            'feeder_id': feeder.id if feeder else False,
            'cart_id': cart.id if cart else False,
            'device_seq': online_material.device_seq if online_material else False,
            'table_no': online_material.table_no if online_material else False,
            'loadpoint': online_material.loadpoint if online_material else False,
            'chanel_sn': online_material.chanel_sn if online_material else False,
            'required_item_code': online_material.required_item_code or online_material.item_code if online_material else False,
            'actual_item_code': material_lot.product_id.default_code if material_lot else False,
            'qty_before': qty_before if qty_before is not False else (online_material.remaining_qty if online_material else 0.0),
            'qty_after': qty_after if qty_after is not False else (online_material.remaining_qty if online_material else 0.0),
            'operator_id': self.env.user.id,
            'operated_at': fields.Datetime.now(),
            'note': note,
            'company_id': mes_order.company_id.id,
        })

    @api.model
    def _sync_feeder_line(self, online_material, material_lot):
        """feeder 管控（mrp.feeder.line）开启时，上料即完成该线的核对。"""
        feeder_line = online_material.feeder_line_ids.filtered(
            lambda line: line.state == 'pending'
        )[:1]
        if not feeder_line:
            return self.env['mrp.feeder.line']
        feeder_line.write({
            'actual_product_id': material_lot.product_id.id,
            'lot_id': material_lot.id,
            'lot_name': material_lot.name,
            'loaded_qty': material_lot.x_smt_point_balance,
            'state': 'verified',
            'verify_datetime': fields.Datetime.now(),
            'verify_user_id': self.env.user.id,
        })
        return feeder_line

    @api.model
    def _bind_feeder(self, feeder, mes_order):
        if not feeder:
            return
        production = mes_order.production_id
        if feeder.bound_production_id and production \
                and feeder.bound_production_id != production:
            raise UserError(_('The feeder is already bound to another MES order.'))
        feeder.write({
            'status': 'in_use',
            'bound_production_id': production.id if production else False,
        })

    @api.model
    def _release_feeder_if_unused(self, feeder):
        if not feeder:
            return
        still_in_use = self.env['sn.smt.online.material'].search_count([
            ('loaded_feeder_id', '=', feeder.id),
            ('is_load', '=', 'Y'),
        ], limit=1)
        if not still_in_use:
            feeder.write({'status': 'normal', 'bound_production_id': False})

    @api.model
    def _load_position(self, mes_order, workcenter, online_material, material_lot,
                       feeder=False, cart=False, operation_type='online_load', note=False,
                       old_material_lot=False, old_lot_qty=0.0):
        self._check_material_common_rules(mes_order, online_material, material_lot)
        remaining_before = online_material.remaining_qty
        online_material.write({
            'loaded_material_lot_id': material_lot.id,
            'loaded_feeder_id': feeder.id if feeder else False,
            'cart_id': cart.id if cart else online_material.cart_id.id if online_material.cart_id else False,
            'workcenter_id': workcenter.id if workcenter else online_material.workcenter_id.id,
            'is_load': 'Y',
            'is_qc_test': 'N',
            'unloaded_at': False,
            'unload_scope': False,
        })
        online_material._set_loaded_quantity(material_lot, operation_type=operation_type)
        lot_vals = {
            'x_smt_is_reel': True,
            'x_smt_reel_state': 'loaded',
        }
        if not material_lot.x_smt_initial_qty:
            lot_vals['x_smt_initial_qty'] = material_lot.x_smt_point_balance
        material_lot.write(lot_vals)
        self._bind_feeder(feeder, mes_order)
        self._sync_feeder_line(online_material, material_lot)
        self._log(
            mes_order, online_material, operation_type,
            material_lot=material_lot, old_material_lot=old_material_lot,
            old_lot_qty=old_lot_qty, feeder=feeder, cart=cart,
            workcenter=workcenter, qty_before=remaining_before,
            qty_after=online_material.loaded_qty, note=note,
        )
        return online_material

    @api.model
    def _release_position(self, mes_order, online_material, operation_type='unload', note=False,
                          keep_feeder=False):
        """下线一个料站：余量保留在卷上（跨制令单累计），不产生损耗记账。"""
        old_lot = online_material.loaded_material_lot_id
        old_feeder = online_material.loaded_feeder_id
        remaining = online_material.remaining_qty
        online_material.write({
            'is_load': 'N',
            'is_qc_test': 'N',
            'loaded_material_lot_id': False,
            'loaded_feeder_id': False,
            'unloaded_at': fields.Datetime.now(),
            'unload_scope': operation_type,
            'last_operation_type': operation_type,
        })
        if not keep_feeder:
            self._release_feeder_if_unused(old_feeder)
        if old_lot:
            old_lot.write({'x_smt_reel_state': 'unloaded'})
        self._log(
            mes_order, online_material, operation_type,
            material_lot=old_lot, feeder=old_feeder,
            qty_before=remaining, qty_after=remaining, note=note,
        )
        return online_material

    # ------------------------------------------------------------------
    # Public API（六动作 + 查询）
    # ------------------------------------------------------------------

    @api.model
    def validate_loading(self, mes_order, workcenter, device_table, loadpoint, feeder_sn=False, material_sn=False):
        """仅校验不落库（REST /api/v1/smt/loading/validate 契约）。"""
        device_seq, table_no = self._parse_device_table(device_table)
        online_material = self._find_position(mes_order, device_seq, table_no, loadpoint)
        feeder = self._resolve_feeder(mes_order, online_material, feeder_sn)
        material_lot = self._resolve_material_lot(mes_order, material_sn)
        self._check_material_common_rules(mes_order, online_material, material_lot)
        return {
            'online_material_id': online_material.id,
            'material_lot_id': material_lot.id,
            'feeder_id': feeder.id if feeder else False,
            'message': 'Validation passed.',
        }

    @api.model
    def save_loading(self, mes_order, workcenter, device_table, loadpoint, feeder_sn=False, material_sn=False):
        """校验并落库（REST /api/v1/smt/loading/save 契约）= 方向B 直接上料。"""
        return self.load_material(mes_order, workcenter, device_table, loadpoint, material_sn, feeder_sn=feeder_sn)

    @api.model
    def load_material(self, mes_order, workcenter, device_table, loadpoint, material_sn, feeder_sn=False):
        """方向B：扫 设备.Table + 料站 +（可选/受控）料枪SN + 物料SN 直接上料。"""
        device_seq, table_no = self._parse_device_table(device_table)
        online_material = self._find_position(mes_order, device_seq, table_no, loadpoint)
        feeder = self._resolve_feeder(mes_order, online_material, feeder_sn)
        material_lot = self._resolve_material_lot(mes_order, material_sn)
        self._load_position(
            mes_order, workcenter, online_material, material_lot,
            feeder=feeder, operation_type='online_load', note='TP',
        )
        return {
            'online_material_id': online_material.id,
            'material_lot_id': material_lot.id,
            'feeder_id': feeder.id if feeder else False,
            'message': 'Online loading saved successfully.',
        }

    @api.model
    def prepare_offline(self, mes_order, cart, feeder_sn, material_sn, slot_no):
        """Online preparation (legacy path): the order is already online,
        the line lands on the cart AND writes a loading log now."""
        feeder = self._resolve_feeder_by_sn(
            (feeder_sn or '').strip(), mes_order.company_id)
        material_lot = self._resolve_material_lot(mes_order, material_sn)
        line = self.env['sn.smt.cart.line'].create({
            'cart_id': cart.id,
            'feeder_id': feeder.id,
            'slot_no': slot_no,
            'material_lot_id': material_lot.id,
            'mes_order_id': mes_order.id,
        })
        position = mes_order.x_smt_online_material_ids.filtered(
            lambda item: item.loadpoint == slot_no
        )[:1]
        self._log(
            mes_order, position, 'offline_prepare',
            material_lot=material_lot, feeder=feeder, cart=cart,
            qty_before=0.0, qty_after=material_lot.x_smt_point_balance, note='BL',
        )
        return {'cart_line_id': line.id, 'online_material_id': position.id if position else False}

    @api.model
    def prepare_offline_stage(self, cart, feeder_sn, material_sn, slot_no, mes_order=False):
        """Offline preparation (PDA): the order may not be online yet --
        only the entity checks run here (feeder resolvable, lot exists,
        cart active). The position matching and material-vs-table checks
        are deferred to load_cart when the cart is mounted."""
        feeder = self._resolve_feeder_by_sn(
            (feeder_sn or '').strip(), cart.company_id)
        material_lot = self.env['stock.lot'].search([
            ('name', '=', (material_sn or '').strip()),
            '|', ('company_id', '=', False),
            ('company_id', '=', cart.company_id.id),
        ], limit=1)
        if not material_lot:
            raise UserError(_('No material lot was found for the material SN.'))
        line = self.env['sn.smt.cart.line'].create({
            'cart_id': cart.id,
            'feeder_id': feeder.id,
            'slot_no': slot_no,
            'material_lot_id': material_lot.id,
            'mes_order_id': mes_order.id if mes_order else False,
        })
        return {'cart_line_id': line.id}

    @api.model
    def _resolve_feeder_by_sn(self, sn, company):
        """PDA scans the CHANNEL SN (not the feeder body SN): channel ->
        feeder; entity checks only (status/maintenance), no
        position-channel or spec matching here."""
        sn = (sn or '').strip()
        if not sn:
            raise UserError(_('The feeder channel SN is required.'))
        channel = self.env['sn.smt.feeder.channel'].search([
            ('channel_sn', '=', sn),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], limit=1)
        feeder = channel.feeder_id if channel else self.env['sn.smt.feeder']
        if not feeder:
            feeder = self.env['sn.smt.feeder'].search([
                ('feeder_sn', '=', sn),
                '|', ('company_id', '=', False), ('company_id', '=', company.id),
            ], limit=1)
        if not feeder:
            raise UserError(_('The feeder channel SN does not exist.'))
        if feeder.status not in ('normal', 'in_use'):
            raise UserError(_('The feeder status is invalid.'))
        if not feeder.maintenance_ok:
            raise UserError(_('The feeder is not available for use because maintenance is not valid.'))
        return feeder

    @api.model
    def load_cart(self, mes_order, workcenter, device_table, cart):
        """方向A第二步：料车上料——车上活动明细逐一落到对应在线料表行。"""
        device_seq, table_no = self._parse_device_table(device_table)
        active_lines = cart._get_active_lines().filtered(lambda line: line.mes_order_id == mes_order)
        if not active_lines:
            raise UserError(_('The cart has no active preparation lines for this MES order.'))
        cart.action_mount(workcenter)
        skipped, loaded = [], []
        for line in active_lines:
            candidates = mes_order.x_smt_online_material_ids.filtered(
                lambda item: item.device_seq == device_seq
                and item.table_no == table_no
                and item.loadpoint == line.slot_no
            )
            target = candidates.filtered(lambda item: item.is_load != 'Y')[:1] or candidates[:1]
            if not target:
                skipped.append(line.slot_no)
                continue
            material_lot = line.material_lot_id
            if material_lot:
                self._load_position(
                    mes_order, workcenter, target, material_lot,
                    feeder=line.feeder_id, cart=cart,
                    operation_type='cart_load', note='LCSL',
                )
            else:
                target.write({
                    'cart_id': cart.id,
                    'workcenter_id': workcenter.id,
                })
                self._log(
                    mes_order, target, 'cart_load',
                    feeder=line.feeder_id, cart=cart, workcenter=workcenter, note='LCSL',
                )
            loaded.append(line.slot_no)
        return {
            'cart_id': cart.id,
            'loaded_slots': loaded,
            'skipped_slots': skipped,
            'message': 'Cart loading completed.',
        }

    @api.model
    def change_material(self, mes_order, workcenter, device_table, loadpoint,
                        new_material_sn, new_feeder_sn=False, change_type=False):
        """换料/续料：同料站旧卷下线（余量保留在卷上），新卷上线并记前物料。
        操作类型自动判定——新卷料号 = 料站要求 → 续料；替代料 → 换料。
        change_type 参数仅为接口兼容保留，传入值不参与判定。"""
        device_seq, table_no = self._parse_device_table(device_table)
        online_material = self._find_position(
            mes_order, device_seq, table_no, loadpoint, require_unloaded=False)
        if online_material.is_load != 'Y':
            raise UserError(_('The current loadpoint is not loaded online.'))
        old_lot = online_material.loaded_material_lot_id
        old_feeder = online_material.loaded_feeder_id
        old_remaining = online_material.remaining_qty
        online_material.replace_count += 1
        online_material.write({
            'is_load': 'N',
            'loaded_material_lot_id': False,
            'loaded_feeder_id': False,
        })
        if old_lot:
            old_lot.write({'x_smt_reel_state': 'unloaded'})
        self._release_feeder_if_unused(old_feeder)
        feeder = self._resolve_feeder(mes_order, online_material, new_feeder_sn)
        material_lot = self._resolve_material_lot(mes_order, new_material_sn)
        # 续料/换料自动判定：新卷料号与料站要求一致 → 续料；替代料 → 换料。
        if (material_lot.product_id.default_code or '') == (online_material.item_code or ''):
            change_type = 'continue'
        else:
            change_type = 'change'
        self._load_position(
            mes_order, workcenter, online_material, material_lot,
            feeder=feeder, operation_type=change_type, note='CHANGE',
            old_material_lot=old_lot, old_lot_qty=old_remaining,
        )
        return {
            'online_material_id': online_material.id,
            'material_lot_id': material_lot.id,
            'old_material_lot_id': old_lot.id if old_lot else False,
            'message': 'Material change completed.',
        }

    @api.model
    def unload(self, mes_order, scope='station', device_table=False, loadpoint=False,
               material_sn=False, cart=False):
        """下料：scope = station（按料站）/ material（按物料SN）/ cart（按料车）/ order（整单）。"""
        lines = mes_order.x_smt_online_material_ids.filtered(lambda line: line.is_load == 'Y')
        if scope == 'station':
            device_seq, table_no = self._parse_device_table(device_table)
            lines = lines.filtered(
                lambda line: line.device_seq == device_seq and line.table_no == table_no
                and (not loadpoint or line.loadpoint == loadpoint)
            )
        elif scope == 'material':
            material_lot = self._resolve_material_lot(mes_order, material_sn)
            lines = lines.filtered(lambda line: line.loaded_material_lot_id == material_lot)
        elif scope == 'cart':
            lines = lines.filtered(lambda line: line.cart_id == cart)
        elif scope != 'order':
            raise UserError(_('The unload scope is invalid.'))
        if not lines:
            raise UserError(_('No loaded SMT material position matches the unload request.'))
        for line in lines:
            self._release_position(mes_order, line, operation_type='unload', note=scope.upper())
        return {'unloaded_qty': len(lines)}

    @api.model
    def changeover(self, source_mes_order, target_mes_order, workcenter):
        """转机继承：同图号新制令单上线，物料留机不重上——
        目标单同料站且物料（含替代料）相符的行直接继承卷/飞达/料车与余量。"""
        if source_mes_order.company_id != target_mes_order.company_id:
            raise UserError(_('The two MES orders must belong to the same company.'))
        if not target_mes_order.x_smt_online_material_ids:
            raise UserError(_('The target MES order has no SMT online material positions.'))
        source_lines = source_mes_order.x_smt_online_material_ids.filtered(lambda line: line.is_load == 'Y')
        if not source_lines:
            raise UserError(_('The source MES order has no loaded SMT material positions.'))
        product_model = self.env['product.product']
        inherited, manual = [], []
        for target_line in target_mes_order.x_smt_online_material_ids.filtered(lambda line: line.is_skip != 'Y'):
            source_line = source_lines.filtered(
                lambda line: line.device_seq == target_line.device_seq
                and line.table_no == target_line.table_no
                and line.loadpoint == target_line.loadpoint
                and (not target_line.chanel_sn or not line.chanel_sn or line.chanel_sn == target_line.chanel_sn)
            )[:1]
            if not source_line or not source_line.loaded_material_lot_id:
                if target_line.is_load != 'Y':
                    manual.append(target_line.loadpoint)
                continue
            loaded_lot = source_line.loaded_material_lot_id
            required_product = product_model.search([
                ('default_code', '=', target_line.item_code),
            ], limit=1)
            allowed = self._is_allowed_material_product(
                target_mes_order, required_product, loaded_lot.product_id)
            if not allowed:
                manual.append(target_line.loadpoint)
                continue
            target_line.write({
                'loaded_material_lot_id': loaded_lot.id,
                'loaded_feeder_id': source_line.loaded_feeder_id.id,
                'cart_id': source_line.cart_id.id,
                'workcenter_id': workcenter.id if workcenter else source_line.workcenter_id.id,
                'is_load': 'Y',
            })
            target_line._set_loaded_quantity(loaded_lot, operation_type='changeover_inherit')
            if target_line.loaded_feeder_id:
                production = target_mes_order.production_id
                target_line.loaded_feeder_id.write({
                    'status': 'in_use',
                    'bound_production_id': production.id if production else False,
                })
            self._log(
                target_mes_order, target_line, 'changeover_inherit',
                material_lot=loaded_lot, feeder=target_line.loaded_feeder_id,
                cart=target_line.cart_id, workcenter=workcenter,
                qty_before=0.0, qty_after=target_line.loaded_qty, note='ZC',
            )
            inherited.append(target_line.loadpoint)
        self.unload(source_mes_order, scope='order')
        return {
            'inherited_slots': inherited,
            'manual_slots': sorted(set(manual)),
            'message': 'Changeover completed.',
        }

    @api.model
    def get_material_status(self, mes_order):
        """PDA 屏显：应上/已上/未上 + 每料站当前状态。"""
        snapshot = self.env['sn.smt.online.material']._get_completion_snapshot(mes_order)
        rows = []
        for line in mes_order.x_smt_online_material_ids.sorted(
            lambda item: (item.device_seq, item.table_no, item.loadpoint, item.id)
        ):
            rows.append({
                'online_material_id': line.id,
                'device_seq': line.device_seq,
                'table_no': line.table_no,
                'loadpoint': line.loadpoint,
                'channel': line.chanel_sn,
                'item_code': line.item_code,
                'point_qty': line.point_qty,
                'loaded_material_lot_name': line.loaded_material_lot_id.name,
                'loaded_feeder_name': line.loaded_feeder_id.feeder_sn,
                'cart_sn': line.cart_id.cart_sn,
                'loaded_qty': line.loaded_qty,
                'remaining_qty': line.remaining_qty,
                'load_status': line.is_load,
                'is_skip': line.is_skip,
                'replace_count': line.replace_count,
            })
        return {
            'mes_order_id': mes_order.id,
            'mes_order_name': mes_order.display_name,
            'material_table_name': mes_order.x_smt_material_table_id.display_name,
            'summary': snapshot,
            'rows': rows,
        }
