from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MesOrderOqcReceiptGate(models.Model):
    """OQC 放行门禁（oqc-disposition-closure 决策 4）：完工、攒托、收货
    创建与最终过账共用同一源校验。仅 station 模式生效——report 模式的
    质量联动保持暂停；无检验义务且无单的制令单不增加质量限制。

    检查在倒冲、收货开单、完工数量累加与库存过账之前执行，失败由
    UserError 冒泡整笔回滚；有现单时以原单快照与未结处置为准（方案
    被停用不能把未结异常变成免检），无现单但命中有效本站方案则报
    待检——门禁不自动代建单、不自动判通过。"""

    _inherit = 'sn.wsd.mes.order'

    def _check_oqc_receipt_release(self, serials=None):
        """同源放行校验：所有入库入口唯一入口（决策 4 表格左列共用）。

        serials：可空的板级明细（攒托包装/收货行 lot 解析出的 SN）；
        提供时追加报废/未结 SN 的逐板拒收，None 时按整单条件检查。"""
        for order in self:
            if order.x_manage_mode != 'station':
                continue  # report 模式：质量联动保持暂停，不加门禁
            inspection = order.x_oqc_inspection_id
            if not inspection:
                scheme = order._oqc_matching_receipt_scheme()
                if scheme:
                    raise UserError(_(
                        'MES order %(order)s falls under outgoing inspection '
                        'plan %(scheme)s (operation %(operation)s): complete '
                        'the outgoing inspection before receiving products.',
                        order=order.name, scheme=scheme.display_name,
                        operation=scheme.operation_id.display_name))
                continue
            # 与处置动作同一锁序列：检查通过后并发 NG 无法插队放行
            inspection._oqc_lock()
            ready, message = inspection._oqc_release_status()
            if not ready:
                raise UserError(_(
                    'Outgoing inspection %(inspection)s has not released MES '
                    'order %(order)s for receipt: %(message)s',
                    inspection=inspection.name, order=order.name,
                    message=message))
            if serials:
                order._check_oqc_receipt_serials(inspection, serials)
        return True

    def _oqc_matching_receipt_scheme(self):
        """本单路线上命中有效 OQC 方案的工序（义务判定）：复用既有方案
        匹配器，只认绑定了工序的生效方案。"""
        self.ensure_one()
        Inspection = self.env['sn.wsd.quality.inspection']
        product = self.production_id.product_id
        for route_op in self.x_route_operation_ids:
            scheme = Inspection._find_scheme(
                'oqc', product=product, route_operation=route_op,
                production=self.production_id)
            if scheme and scheme.operation_id:
                return scheme
        return False

    def _check_oqc_receipt_serials(self, inspection, serials):
        """板级拒收（决策 4）：已报废或当前未获准接收的 SN 不能随批
        入库；无台级明细的数量收货走整单条件，不进这里。"""
        self.ensure_one()
        Serial = self.env['sn.wsd.serial.identity']
        scrapped = serials.filtered(
            lambda sn: sn.x_quality_hold_state == 'scrapped')
        dispositions = inspection._oqc_current_dispositions(serials=serials)
        scrapped |= Serial.browse([
            sid for sid, info in dispositions.items()
            if info.get('state') == 'scrapped'])
        if scrapped:
            raise UserError(_(
                'Serial number(s) %(sn)s are scrapped and cannot be '
                'received.', sn=', '.join(sorted(scrapped.mapped('name')))))
        unresolved = Serial.browse([
            sid for sid, info in dispositions.items()
            if info.get('state') in ('pending', 'reworking',
                                     'awaiting_reinspection')])
        if unresolved:
            raise UserError(_(
                'Serial number(s) %(sn)s still have an open outgoing '
                'inspection disposition.',
                sn=', '.join(sorted(unresolved.mapped('name')))))
        return True

    # ------------------------------------------------------------------
    # 入库入口接线（决策 4）：倒冲/收货/数量累加之前，super 之前
    # ------------------------------------------------------------------
    def action_complete(self, qty, destination='stock', workshop=False):
        # 手动完工与车间终端完工的唯一执行入口：拒绝时无倒冲、无收货
        # 单、无完工数量变更（线边直验同在此入口内）
        self._check_oqc_receipt_release()
        return super().action_complete(
            qty, destination=destination, workshop=workshop)

    def _mes_create_receipt(self, qty, destination, workshop=False):
        # 同源复查：绕过 action_complete 的内部直调也不能缺检开单
        self._check_oqc_receipt_release()
        return super()._mes_create_receipt(
            qty, destination, workshop=workshop)

    def _mes_create_pallet_receipt(self, qty, cartons, origin_pallets=False):
        serials = cartons.x_meter_pack_record_ids.mapped(
            'serial_identity_id')
        self._check_oqc_receipt_release(serials=serials)
        return super()._mes_create_pallet_receipt(
            qty, cartons, origin_pallets=origin_pallets)


class CartonPalletBindingLogOqcGate(models.Model):
    """攒托入库门禁（决策 4）：order_map 聚合完成、倒冲循环开始前，
    对全部制令单预检查——任一未放行整批拒绝，事务回滚后两单均不
    倒冲、数量不变、托盘保持 closed。"""

    _inherit = 'sn.wsd.carton.pallet.binding.log'

    def _check_receipt_release(self, order_map):
        for order in order_map:
            order._check_oqc_receipt_release()
        return True


class StockPickingOqcGate(models.Model):
    """收货单最终过账门禁（决策 4）：开单时与最终过账时分别复查——
    已开未过账的收货单不能借开单时的旧判定绕过重开后的新异常。

    识别必须精确：仅认 MES 完工收货类型（仓库专设
    picking_type_receipt_id）且带制令单引用的 picking；领料/补料/
    退料/采购/普通调拨一律不拦。"""

    _inherit = 'stock.picking'

    def _oqc_is_mes_receipt(self):
        self.ensure_one()
        if not self.x_mes_order_id or not self.picking_type_id:
            return False
        warehouse = (self.picking_type_id.warehouse_id
                     or self.location_id.warehouse_id
                     or self.location_dest_id.warehouse_id)
        return bool(warehouse and warehouse.picking_type_receipt_id
                    and self.picking_type_id == warehouse.picking_type_receipt_id)

    def _oqc_receipt_gate_serials(self):
        """收货明细的板级 SN：从 move line 的台级 lot（码=表 SN）解析；
        数量收货（无台级 lot）返回空集，走整单条件检查。"""
        self.ensure_one()
        lot_names = self.move_ids.move_line_ids.lot_id.mapped('name')
        if not lot_names:
            return self.env['sn.wsd.serial.identity']
        return self.env['sn.wsd.serial.identity'].search([
            ('name', 'in', lot_names),
            ('company_id', '=', self.company_id.id),
        ])

    def _action_done(self):
        # button_validate 的 _pre_action_done_hook 只覆盖界面路径；后台
        # 直调 _action_done 不过钩子——在 stock move 落账之前复查放行
        # 状态，两条路径共用这一处检查（已开未过账单不能借旧判定绕过
        # 重开后的新异常）
        for picking in self.filtered(
                lambda p: p.state != 'done' and p._oqc_is_mes_receipt()):
            picking.x_mes_order_id._check_oqc_receipt_release(
                serials=picking._oqc_receipt_gate_serials())
        return super()._action_done()
