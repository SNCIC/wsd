from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MesOrderOqc(models.Model):
    """出厂检（OQC）接线（oqc-entry-trigger）：投入/报工触发建单
    （AQL 批量=工单数量）、投入限流（满 n 拦）、出站登记、判定联动。
    与 FAI 状态机同构但有两个刻意分叉（决策 2/3）：
    ① 一单一工单一张 OQC 单，无轮次字段，判退不自动开新一轮——
    放行路径只有 action_reset_open 重开复检或 action_mark_concession
    让步（均为现有方法）；② NG 样本不剔除、名额不释放——补位会破坏
    AQL 缺陷计数 d。全部钩子在质量模块继承制令单实现，sn_wsd_mrp
    主链不感知 OQC。"""

    _inherit = 'sn.wsd.mes.order'

    x_oqc_inspection_ids = fields.One2many(
        'sn.wsd.quality.inspection', 'mes_order_id',
        string='Outgoing Inspections',
        domain=[('inspection_type', '=', 'oqc')],
    )
    x_oqc_state = fields.Selection(
        [('none', 'None'), ('in_progress', 'In Progress'),
         ('passed', 'Passed')],
        string='OQC Status', compute='_compute_x_oqc',
    )
    x_oqc_inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection', string='Current OQC Inspection',
        compute='_compute_x_oqc',
    )

    @api.depends('x_oqc_inspection_ids.state',
                 'x_oqc_inspection_ids.result',
                 'x_oqc_inspection_ids.x_oqc_ng_serial_ids',
                 'x_oqc_inspection_ids.x_oqc_disposition_event_ids')
    def _compute_x_oqc(self):
        # inspection._order = scheduled_time desc, id desc → 列表首个即最新；
        # 一单一工单一张 OQC 单（无轮次），防御性取最新一张
        for order in self:
            inspections = order.x_oqc_inspection_ids
            current = inspections[:1]
            order.x_oqc_inspection_id = current
            if not inspections:
                state = 'none'
            elif current._oqc_passed():
                # 真实放行口径（任务 2.2）：done 且 result ∈ (pass,
                # concession) 且无未结处置——让步放行也算通过；放行后
                # 新 NG（pending）会把徽标拉回 in_progress
                state = 'passed'
            else:
                state = 'in_progress'
            order.x_oqc_state = state

    # ------------------------------------------------------------------
    # 触发：首次投入配置工序 / 首次合格报工（惰性建单，AQL 快照）
    # ------------------------------------------------------------------
    def _oqc_maybe_open_round(self, route_operation):
        """惰性建单（决策 1/2）：命中配了工序的生效 oqc 方案才建；
        一单一工单一张——已存在任意状态的 OQC 单即返回（判退不开新
        一轮）。批量显式传工单计划数量，AQL 链路（_get_lot_qty_from_values
        对显式 lot_qty 短路）在建单时固化样本数 n 与 Ac/Re 快照。"""
        self.ensure_one()
        Inspection = self.env['sn.wsd.quality.inspection']
        scheme = Inspection._find_scheme(
            'oqc', product=self.production_id.product_id,
            route_operation=route_operation,
            production=self.production_id)
        if not scheme or not scheme.operation_id:
            return Inspection  # 未命中方案 / 方案未配工序 → 静默不触发
        existing = self.x_oqc_inspection_ids
        if existing:
            return existing[:1]
        route_op = self.x_route_operation_ids.filtered(
            lambda r: r.operation_id == scheme.operation_id)[:1]
        values = {
            'mes_order_id': self.id,
            'production_id': self.production_id.id,
            'product_id': self.production_id.product_id.id,
            'production_line_id': self.production_line_id.id,
            'route_operation_id': route_op.id,
            # AQL 批量 = 工单数量（决策 2）：显式传值绕过 lot_qty_source
            # 各口径（含 'mes_order' 的过站历史优先），快照固定为计划量
            'lot_qty': int(round(self.planned_qty or 0.0)),
        }
        # 两种模式都不预生成单据级样本行（关闭系统抽选）：过站样本 =
        # 投入站扫码挑样（台账在 x_fai_* m2m 字段上），报工抽检进度 =
        # x_fai_reported_qty 数量口径（d 走缺陷行合计，扫不良板按需落行）
        values['sample_selection_method'] = 'manual'
        return Inspection.create_from_scheme(scheme, values)

    # ------------------------------------------------------------------
    # 投入限流（仅过站模式）：满 n 且未判定通过（含已判退）拦，
    # pass/concession 放行整单；闸门在 super 前、建单+登记在 super 后
    # ------------------------------------------------------------------
    def enter_station(self, serial_identity, route_operation,
                      workcenter=False):
        self.ensure_one()
        # OQC 返工授权（任务 5.3，决策 3）：活跃凭证的板在重走路线时，
        # 与维修回流共用同一 cutoff/seed 合并钩子——截断点取本次返工
        # 发起时间且全程生效（中间进度只认发起后的 OK，旧已关维修单
        # 的截断点被本次覆盖）；进站种子只对本次目标工序放行，其余
        # 工序按"截断点后有 OK 前驱"推进。次数上限豁免由内核凭证口径
        # 承担（mes_order.py:903）。复测授权的过站（任务 4.3）带
        # sn_wsd_oqc_retest_pass 标志跳过本注入
        if self.x_manage_mode == 'station' \
                and serial_identity.x_rework_inspection_id \
                and serial_identity.x_rework_order_id == self \
                and not self.env.context.get('sn_wsd_oqc_retest_pass'):
            auth_ctx = {
                # 截断点：时间口径激活严格重走模式；水位线口径精确区分
                # 旧 OK 与本次重走（同秒内时间戳分不开，任务 5.3）
                'sn_wsd_pass_cutoff': fields.Datetime.subtract(
                    serial_identity.x_rework_started_at, seconds=1)
                if serial_identity.x_rework_started_at else False,
                'sn_wsd_pass_cutoff_min_id':
                    serial_identity.x_rework_history_watermark or 0,
            }
            if route_operation.id == serial_identity.x_rework_operation_id.id:
                auth_ctx['sn_wsd_repair_seed_ids'] = [
                    serial_identity.x_rework_operation_id.id]
            self = self.with_context(**auth_ctx)
        if self.x_manage_mode == 'station':
            self._oqc_gate_feeding(serial_identity, route_operation)
        res = super().enter_station(
            serial_identity, route_operation, workcenter=workcenter)
        if self.x_manage_mode == 'station':
            self._oqc_register_sample(serial_identity, route_operation)
        return res

    def _oqc_gate_feeding(self, serial_identity, route_operation):
        self.ensure_one()
        inspection = self.x_oqc_inspection_id
        if not inspection or inspection._oqc_passed():
            return
        if inspection.x_full_inspection:
            return  # 判退批次整批全检：放行逐台过站逐台判定
        if route_operation.operation_id != inspection.scheme_id.operation_id:
            return  # 只在 OQC 工序的投入口限流，其余工序照常过站
        if serial_identity in inspection.x_fai_serial_ids:
            return  # 已登记样本（复测/回流）放行
        if len(inspection.x_fai_serial_ids) >= inspection.sample_size:
            raise ValidationError(_(
                'Outgoing inspection is in progress on MES order '
                '%(order)s: wait for the inspection result before feeding '
                'more serial numbers.', order=self.name))

    def _oqc_register_sample(self, serial_identity, route_operation):
        self.ensure_one()
        inspection = self.x_oqc_inspection_id
        if not inspection:
            inspection = self._oqc_maybe_open_round(route_operation)
        if not inspection or inspection._oqc_passed():
            # 判定通过后投入恢复整单自由放行，不再登记样本
            return
        if inspection.x_full_inspection:
            # 台账口径（oqc-full-lot-form）：全检下不登记样本名单
            # （闸门走开关；判定以过站历史为准，名单不再积累万台 m2m）
            return
        if route_operation.operation_id != inspection.scheme_id.operation_id:
            return
        if serial_identity not in inspection.x_fai_serial_ids:
            # 样本台账复用 FAI 的 x_fai_* 字段族（决策 5）
            inspection.x_fai_serial_ids = [(4, serial_identity.id)]

    # ------------------------------------------------------------------
    # 出站登记（与 FAI 的分叉点，决策 3）：OK → 到检登记 + 矩阵展开；
    # NG/报废 → 计入不良名单，名额保持占用（不剔除、不补位、维修
    # 回流不回补——补位会一直抽到凑满良品、AQL 缺陷计数失真）
    # ------------------------------------------------------------------
    def leave_station(self, serial_identity, result, scrap_reason=False,
                      ng_defect=False, operator_code=False, workcenter=False):
        self.ensure_one()
        # super 之后 WIP 已流转，工序实例要在之前取（同 FAI）
        wip = self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ], limit=1)
        route_operation = wip.route_operation_id if wip else False
        res = super().leave_station(
            serial_identity, result, scrap_reason=scrap_reason,
            ng_defect=ng_defect, operator_code=operator_code,
            workcenter=workcenter)
        if route_operation:
            self._oqc_on_leave(serial_identity, result, route_operation,
                               ng_defect=ng_defect)
        return res

    def _oqc_on_leave(self, serial_identity, result, route_operation,
                      ng_defect=False):
        self.ensure_one()
        inspection = self.x_oqc_inspection_id
        if not inspection:
            return
        if route_operation.operation_id != inspection.scheme_id.operation_id:
            return  # 非 OQC 工序的出站不参与样本判定
        # 真实放行口径（任务 2.2）：done/pass|concession 且（除正在出站的
        # 这块板外）无未结处置才算 released——放行后本站新 NG 仍要登记
        # detected 并把 release_ready 翻 False，不能被早退吃掉（spec「批次
        # 释放后出现的新 NG」）。忽略本板是刻意的：本板自己的新 NG 事实
        # 已把它自己的"放行"翻 False，不能反过来吞掉自己的登记
        released = (inspection.state == 'done'
                    and inspection.result in ('pass', 'concession')
                    and inspection._oqc_released_except(serial_identity))
        active_voucher = (
            serial_identity.x_rework_inspection_id == inspection.id)
        if inspection.x_full_inspection and result == 'ok'                 and not active_voucher:
            # 台账口径（oqc-full-lot-form）：合格板判定 = 出站 OK（过站
            # 历史即台账），不铺格不登到检——只有异常板才细记（含放行后
            # OK 重过站：无异常事实，无事可做）。返工回流板不跳过：早退
            # 会漏掉 rework_arrive 收口（任务 3.2「全检返工板 OK 不被
            # 早退遗漏」）
            return
        if serial_identity not in inspection.x_fai_serial_ids \
                and not inspection.x_full_inspection and not released:
            return  # 台账下 NG 板不入名单也要细记（名单只在抽样登记）
        if result == 'ok':
            if released and not active_voucher:
                # 放行后 OK 重过站照旧无事可做：不重复登记到检/铺格
                # （返工回流板除外——同上，voucher 未关必须收口）
                return
            if serial_identity not in inspection.x_fai_arrived_serial_ids:
                inspection.x_fai_arrived_serial_ids = [(4, serial_identity.id)]
            # 复检合格（回流板重过质检工序 OK）：从 NG 名单剔除；该板是否
            # 退出 d 由处置状态决定（显式 retest/让步/报废事件），出站 OK
            # 本身不再销项——首次 NG 记录留在过站历史（x_is_rework 行）
            inspection.x_oqc_ng_serial_ids = [
                (3, serial_identity.id)]
            # 到检即展开该样本 × 全部检验项的结果格（幂等，仅过站模式，
            # 已泛化到 oqc），默认全部合格，检验员只改异常格
            inspection._fai_expand_result_cells()
        else:
            # NG/报废：计入不良名单参与 d 与 Ac/Re 判定，样本名额
            # 刻意保持占用（FAI 在此剔除释放名额，OQC 不做）；放行后的
            # 新 NG 同样登记（released 也不例外，见上方早退修复）
            inspection.x_oqc_ng_serial_ids = [(4, serial_identity.id)]
            # 初检 NG 落格：走异常板显式铺格（oqc-disposition-closure
            # 任务 1.4）——不把板加进抽样名单，全检新 NG 与名单内 NG
            # 同一条路径；处置结案只认显式处置事件（任务 2.2），格子改回
            # pass 不再自动剔 NG 名单
            inspection._oqc_ensure_cells(serial_identity)
            # 程序化写 fail 携带静音标志抑制通用格钩子：detected 事件
            # 由下方 _oqc_log_detected_from_history 自己记，避免双事件
            inspection.cell_ids.with_context(
                sn_wsd_oqc_cell_silent=True).filtered(
                lambda c, sn=serial_identity: c.serial_identity_id == sn
            ).write({'manual_result': 'fail'})
            # 处置审计（任务 1.4）：设备/过站 NG 落 detected 事件，
            # state_after=pending，source_key 用过站历史身份（幂等）。
            # 返工重走板的失败重判不在此记——凭证块落 rework_ng（任务
            # 5.4），再记 detected 会把 reworking 覆盖成 pending
            if serial_identity.x_rework_inspection_id != inspection.id:
                inspection._oqc_log_detected_from_history(
                    serial_identity, route_operation)
        # 回流板复检落定：OK = 追加 rework_arrive 事件（reworking →
        # awaiting_reinspection，批次 3 的复测确认在此状态上收口），NG =
        # 回到处置决策；出站即关闭回流凭证——豁免次数上限的既有口径，
        # 批次 3 把凭证保留挪到复测确认（决策 3）
        if serial_identity.x_rework_inspection_id == inspection.id:
            info = inspection._oqc_current_dispositions(
                serial_identity).get(serial_identity.id) or {}
            if result == 'ok' and info.get('state') == 'reworking':
                # 返工板回站 OK → 待复检（rework_arrive）。凭证保留到
                # 检验员明确复测确认通过才清（任务 5.4：重判通过才清
                # 凭证）；复测授权板（pending）不在此处收口——它的
                # retest 事件由复测服务按格判定后追加（任务 4.3）
                inspection._oqc_append_events([{
                    'serial_identity_id': serial_identity.id,
                    'action': 'rework_arrive',
                    'state_before': info['state']
                    if info.get('event_id') else False,
                    'state_after': 'awaiting_reinspection',
                    'attempt_no': serial_identity.x_rework_count or 0,
                    'reason': 'Reworked board re-passed the inspection '
                              'operation with OK; re-judgment pending.',
                    'before_snapshot': dict(inspection._oqc_batch_snapshot(),
                                            source='rework_arrive'),
                    'after_snapshot': dict(
                        inspection._oqc_batch_snapshot(),
                        **inspection._oqc_cell_snapshot(serial_identity)),
                    'route_operation_id': route_operation.id,
                    'source_key': 'oqc-rework-arrive-%s-%s-%s' % (
                        inspection.id, serial_identity.id,
                        serial_identity.x_rework_count),
                }])
                # 凭证保留：awaiting_reinspection 期间放行/完成/让步
                # 均被状态拦截，重走豁免只对返工范围有效
            elif result in ('ng', 'scrap') and info.get('state') in (
                    'reworking', 'awaiting_reinspection'):
                # 再次 NG（任务 5.4）：结束本次返工尝试、板回待处置，
                # 次数保留，可再次返工/报废/让步；凭证关闭
                inspection._oqc_append_events([{
                    'serial_identity_id': serial_identity.id,
                    'action': 'rework_ng',
                    'state_before': info['state'],
                    'state_after': 'pending',
                    'attempt_no': serial_identity.x_rework_count or 0,
                    'reason': 'Reworked board failed the inspection '
                              'operation again; back to disposition.',
                    'defect_code_id': ng_defect.id if ng_defect else False,
                    'before_snapshot': dict(inspection._oqc_batch_snapshot(),
                                            source='rework_ng'),
                    'after_snapshot': dict(
                        inspection._oqc_batch_snapshot(),
                        **inspection._oqc_cell_snapshot(serial_identity)),
                    'route_operation_id': route_operation.id,
                    'source_key': 'oqc-rework-ng-%s-%s-%s-%s' % (
                        inspection.id, serial_identity.id,
                        serial_identity.x_rework_count,
                        route_operation.id),
                }])
                serial_identity.x_rework_inspection_id = False
                serial_identity.x_rework_operation_id = False

    # ------------------------------------------------------------------
    # 报工模式数量收集器（决策 2）：首次合格报工建单（基数快照 0）、
    # 超额整笔拦（上限 = AQL 样本量 n）；NG/报废报工不占名额
    # ------------------------------------------------------------------
    # DISABLED 2026-10-29 report-daily-workbench: reporting no longer feeds
    # OQC (no sampling document, no AQL snapshot, no throttle on qualified
    # reports) while the daily workbench change is live; the station paths
    # (_oqc_register_sample / _oqc_gate_feeding) are untouched
    # (restore: wsd-doc/openspec/changes/report-daily-workbench/design.md sec.5)
    # def report_operation_qty(self, route_operation, qty_ok, qty_ng=0.0,
    #                          qty_scrap=0.0, scrap_reason=False):
    #     self.ensure_one()
    #     self._oqc_gate_report(route_operation, qty_ok)
    #     return super().report_operation_qty(
    #         route_operation, qty_ok, qty_ng=qty_ng, qty_scrap=qty_scrap,
    #         scrap_reason=scrap_reason)
    #
    # def _oqc_gate_report(self, route_operation, qty_ok):
    #     self.ensure_one()
    #     if self.x_manage_mode != 'report' or qty_ok <= 0:
    #         return  # 纯 NG/报废报工：调机记账，不占样本名额（同 FAI）
    #     inspection = self.x_oqc_inspection_id
    #     if not inspection:
    #         # 无单先建：报工模式同样触发（基数快照 0 = 从头累计），
    #         # 再按同一额度口径校验本笔
    #         inspection = self._oqc_maybe_open_round(route_operation)
    #     if not inspection or inspection._oqc_passed():
    #         return
    #     if route_operation.operation_id != inspection.scheme_id.operation_id:
    #         return  # 只拦 OQC 工序的报工
    #     remaining = inspection.sample_size - inspection.x_fai_reported_qty
    #     if qty_ok > remaining + 0.0001:
    #         raise ValidationError(_(
    #             'Outgoing inspection is in progress on MES order '
    #             '%(order)s: report at most %(remaining)s OK unit(s) in '
    #             'this batch.', order=self.name, remaining=max(remaining, 0.0)))

    # ------------------------------------------------------------------
    # 可见性：出厂检验单入口（视图徽标/按钮由 batch 4 接线）
    # ------------------------------------------------------------------
    def action_open_oqc_inspections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Outgoing Inspections'),
            'res_model': 'sn.wsd.quality.inspection',
            'view_mode': 'list,form',
            'domain': [('mes_order_id', '=', self.id),
                       ('inspection_type', '=', 'oqc')],
            'context': {'default_mes_order_id': self.id,
                        'default_inspection_type': 'oqc'},
        }


class QualityInspectionOqc(models.Model):
    """OQC 判定收口（oqc-entry-trigger 决策 3 + oqc-disposition-closure
    任务 2.2/2.3）：批次判定与处置放行分离——result 只回答 AQL 批结论，
    真实放行（_oqc_passed）还要求无 pending/reworking/awaiting_
    reinspection 的已知处置。抽样完检允许先得出 reject、Ac>0 时 pass 与
    pending 共存；全检完检强制已知异常全结。判退不自动开新一轮，放行
    路径是原单处置（重开复检 / 整批让步向导）。"""

    _inherit = 'sn.wsd.quality.inspection'

    def _oqc_passed(self):
        """真实放行口径（任务 2.2）：state=done 且 result ∈ (pass,
        concession) 且无 pending/reworking/awaiting_reinspection 的已知
        处置（复用 _oqc_release_status）。批次判定字段（result）不动
        语义——界面仍显示原批次判定；判退与 pass+pending 都保持投入
        限流。非过站矩阵单（report/手工 IQC 等）保持旧的二元口径。"""
        self.ensure_one()
        if self.state != 'done' or self.result not in ('pass', 'concession'):
            return False
        if not self._oqc_station_mode():
            return True
        ready, _message = self._oqc_release_status()
        return ready

    def action_done(self):
        # OQC 收口（任务 2.2）：处置结案只认显式处置事件（retest/
        # concession/scrap，后续批次接动作），旧"缺 fail 即销项"收敛已
        # 移除——格子改回 pass 不再自动剔 NG 名单
        full_close_notes = {}
        for inspection in self.filtered(
                lambda i: i.inspection_type == 'oqc' and i.state != 'done'
                and i.mes_order_id
                and i.mes_order_id.x_manage_mode != 'report'):
            open_groups = inspection._oqc_open_disposition_serials()
            if inspection.x_full_inspection:
                # 全检模式：完成必须所有已知异常已结（pending/reworking/
                # awaiting_reinspection 任一存在即拒绝；Ac 允许值不作为
                # 忽略已知异常的理由）
                if open_groups:
                    raise UserError(_(
                        'Outgoing inspection: known abnormal boards are '
                        'not fully disposed yet — %s. Finish their '
                        'disposition before closing the full-lot '
                        'inspection.',
                        inspection._oqc_open_disposition_summary(open_groups)))
                # 数量差异收口（任务 3.3）：已检（按 SN 去重）< 批量时，
                # 提示差异并要求非空收口理由（向导确认带 context 传入）；
                # 该确认只处理数量差异，不能越过上面的未结硬拦
                inspected = len(inspection._oqc_full_inspected_serials())
                lot_qty = int(inspection.lot_qty or 0)
                if inspected < lot_qty:
                    reason = (self.env.context.get(
                        'sn_wsd_oqc_full_close_reason') or '').strip()
                    if not reason:
                        raise UserError(_(
                            'Outgoing inspection: %(inspected)s of %(lot)s '
                            'boards of MES order %(order)s have been '
                            'inspected on the full-lot inspection. Confirm '
                            'the gap of %(gap)s board(s) with the quantity '
                            '-gap closure dialog and state why the lot '
                            'closes at %(inspected)s.',
                            inspected=inspected, lot=lot_qty,
                            gap=lot_qty - inspected,
                            order=inspection.mes_order_id.name))
                    full_close_notes[inspection.id] = {
                        'inspected': inspected, 'lot': lot_qty,
                        'reason': reason}
            else:
                # 抽样模式齐套守卫保留：到检 ∪ NG 名单 ≥ 样本量 n（NG 板
                # 占名额，d 由它们贡献）；Ac>0 时允许 pass 与 pending 共存
                # （放行由 x_oqc_release_ready 单独把关），也允许先 reject
                arrived = len(inspection.x_fai_arrived_serial_ids
                              | inspection.x_oqc_ng_serial_ids)
                if arrived < inspection.sample_size:
                    raise UserError(_(
                        'Outgoing inspection: only %(arrived)s of %(need)s '
                        'samples reached the outgoing operation; wait for '
                        'the full sample set.', arrived=arrived,
                        need=inspection.sample_size))
                # 批次判定与处置放行分离（任务 5.5）：返工中/待复检的板
                # 不拦批次结论——单据可先判 pass/reject（「批次合格、处置
                # 未完成」），放行由 x_oqc_release_ready 单独拦；处置动作
                # 在 done 单上仍可执行（自动重开，任务 2.2）
        # 判退不在此开新一轮（决策 3）：reject 联动（hold + 质量 issue
        # 转维修）由既有 _apply_quality_hold 在 super 链路内完成
        result = super().action_done()
        # 数量差异收口留痕（任务 3.3）：full_close 批次事件记实际已检数
        # 与理由，操作人与时间由事件服务端记录
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        for inspection in self.browse(sorted(full_close_notes)):
            note = full_close_notes[inspection.id]
            inspection._oqc_lock()
            token = Event.search([
                ('inspection_id', '=', inspection.id)],
                order='id desc', limit=1).id or 0
            inspection._oqc_append_events([{
                'action': 'full_close',
                'reason': note['reason'],
                'before_snapshot': inspection._oqc_batch_snapshot(),
                'after_snapshot': inspection._oqc_full_close_snapshot(
                    note['inspected'], note['lot'], note['reason']),
                'source_key': 'oqc-full-close-%s-%s' % (inspection.id, token),
            }])
        return result

    def action_set_all_pass(self):
        # 全部合格捷径（任务 2.2）：存在未结处置板时拒绝——批量改 pass
        # 不能代替逐板确认复测（「改格或全部合格不等于复测结案」），
        # 报错指向按板确认；无未结异常的正常检验照旧可用。批量合格
        # （action_batch_set_pass）内部复用本入口，同样被拦
        for inspection in self.filtered(
                lambda i: i._oqc_station_mode()):
            open_groups = inspection._oqc_open_disposition_serials()
            if open_groups:
                raise UserError(_(
                    'Inspection %s still has boards not fully disposed '
                    '(%s): confirm their retest board by board instead of '
                    'using the all-pass shortcut.',
                    inspection.name,
                    inspection._oqc_open_disposition_summary(open_groups)))
        return super().action_set_all_pass()

    def action_concession(self):
        """让步入口（任务 2.3）：OQC 过站矩阵单改走"必填理由 + 范围确认"
        向导；其余类型保持一键让步的旧路径。"""
        self.ensure_one()
        if self._oqc_station_mode():
            return {
                'type': 'ir.actions.act_window',
                'name': _('Batch Concession'),
                'res_model': 'sn.wsd.quality.oqc.concession.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_inspection_id': self.id},
            }
        return self.action_mark_concession()

    def action_mark_concession(self):
        # 一键让步对 OQC 过站矩阵单关闭（任务 2.3）：缺理由与范围确认的
        # 让步会绕过硬拦校验，直调拒绝并指向向导；其他类型保持原行为
        station_oqc = self.filtered(lambda i: i._oqc_station_mode())
        if station_oqc:
            raise UserError(_(
                'Outgoing inspections of station-mode MES orders accept '
                'concessions through the batch concession wizard (reason '
                'and scope confirmation), not the one-click mark.'))
        return super().action_mark_concession()

    def _apply_quality_hold(self):
        # 判退不再自动 hold/开质量 issue（oqc-ng-disposition 口径修正）：
        # NG 板的出路是处置动作（复测/回流/报废/让步），自动冻结会把
        # 回流重走拦死（板带着 hold 出不了站）。维修侧需要单据时由维修
        # 工单人工报修自建（ca463b9 方向）。super 的缺陷行口径保留给
        # IQC 等非过站矩阵单据。
        others = self.filtered(
            lambda i: not (i._oqc_station_mode()
                           and i.result in ('fail', 'reject')))
        return super(QualityInspectionOqc, others)._apply_quality_hold()

    @api.depends(
        'inspection_type', 'mes_order_id.x_manage_mode',
        'sample_ids.result', 'sample_ids.serial_identity_id',
        'sample_ids.qty', 'sample_ids.defect_code_id', 'x_picked_qty',
        'x_fai_reported_qty',
        'x_fai_arrived_serial_ids', 'x_oqc_ng_serial_ids',
        'cell_ids.result', 'cell_ids.serial_identity_id',
        'defect_line_ids.serial_identity_id',
        'x_oqc_disposition_event_ids',
    )
    def _compute_sample_counts(self):
        # OQC 建单时关了系统抽选（无预生成样本行）：把共享的
        # sample_checked_qty / sample_defect_qty 对齐到真实台账，让
        # sampling.py 的完检闸门（checked ≥ n）与展示读到 OQC 口径——
        # 过站 = 到检 ∪ NG 名单 / 当前有效不良 SN 去重（任务 2.2：处置
        # 结案后 d 自动重算）；报工 = 已抽数量 / 扫码落下的不良行
        # （Ac/Re 判定的 d 在报工模式走 defect_qty 缺陷行合计，由
        # sample_ids 为空时的既有回退路径承接）
        super()._compute_sample_counts()
        for inspection in self.filtered(
                lambda i: i.inspection_type == 'oqc' and i.mes_order_id):
            if inspection._oqc_station_mode():
                if inspection.x_full_inspection:
                    # 全检台账（任务 3.3）：已检 = OQC 工序终态过站 SN
                    # 去重（合格板不登名单，历史即台账）；完检闸门对
                    # 全检不套 n（sampling.action_done 已豁免），此计数
                    # 仅用于展示与 d 判定
                    inspection.sample_checked_qty = len(
                        inspection._oqc_full_inspected_serials())
                else:
                    inspection.sample_checked_qty = len(
                        inspection.x_fai_arrived_serial_ids
                        | inspection.x_oqc_ng_serial_ids)
                inspection.sample_defect_qty = len(
                    inspection._oqc_bad_serial_ids())
            else:
                inspection.sample_checked_qty = int(
                    inspection.x_fai_reported_qty or 0.0)
                inspection.sample_defect_qty = len(
                    inspection.sample_ids.filtered(
                        lambda s: s.result == 'fail'))


class MesOrderRouteOperationOqcConcession(models.Model):
    """让步路线授权（oqc-disposition-closure 决策 3 末段，任务 2.3）：
    OQC 工序行 result='ng' 的 SN，若其在本单 OQC 检验单的最新处置状态为
    concession，则该 OQC 工序计入完成集——后继工序可达性放行。仅对该
    OQC 工序生效，不改写 NG 行本身（NG 仍是真实测试事实），不扩展到
    其他工序/其他单；workorder 侧 finished 判定不受影响（让步板最新行
    仍 ng → 不算 finished，刻意的：让步板靠入库放行）。"""

    _inherit = 'sn.wsd.mes.order.route.operation'

    def _completed_operations(self, mes_order, serial_identity=None):
        done = super()._completed_operations(mes_order, serial_identity)
        if mes_order.x_manage_mode == 'report' or not serial_identity:
            return done
        inspection = mes_order.x_oqc_inspection_id
        if not inspection or not inspection._oqc_station_mode():
            return done
        oqc_rows = self.filtered(
            lambda r, order=mes_order, insp=inspection:
                r.mes_order_id == order
                and r.operation_id == insp.scheme_id.operation_id)
        if not oqc_rows or oqc_rows & done:
            return done
        # 让步是当次 OQC 检验单的背书（授权来源是处置事件，不是过站
        # 时间窗）：不受维修 cutoff 语义影响，直接按处置状态并入完成集
        info = inspection._oqc_current_dispositions(
            serial_identity).get(serial_identity.id) or {}
        if info.get('state') == 'concession':
            done |= oqc_rows
        return done
