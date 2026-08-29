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
                 'x_oqc_inspection_ids.result')
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
                # 判定通过口径：done 且 result ∈ (pass, concession)——
                # 让步放行也算通过，整单解锁（决策 2）
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
        if not self.x_online_date:
            return Inspection
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
        if route_operation.operation_id != inspection.scheme_id.operation_id:
            return  # 只在 OQC 工序的投入口限流，其余工序照常过站
        if serial_identity in inspection.x_fai_serial_ids:
            return  # 已登记样本（复测回流）放行
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
                      ng_defect=False, operator_code=False):
        self.ensure_one()
        # super 之后 WIP 已流转，工序实例要在之前取（同 FAI）
        wip = self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ], limit=1)
        route_operation = wip.route_operation_id if wip else False
        res = super().leave_station(
            serial_identity, result, scrap_reason=scrap_reason,
            ng_defect=ng_defect, operator_code=operator_code)
        if route_operation:
            self._oqc_on_leave(serial_identity, result, route_operation)
        return res

    def _oqc_on_leave(self, serial_identity, result, route_operation):
        self.ensure_one()
        inspection = self.x_oqc_inspection_id
        if not inspection or inspection._oqc_passed():
            return
        if serial_identity not in inspection.x_fai_serial_ids:
            return
        if route_operation.operation_id != inspection.scheme_id.operation_id:
            return  # 非 OQC 工序的出站不参与样本判定
        if result == 'ok':
            if serial_identity not in inspection.x_fai_arrived_serial_ids:
                inspection.x_fai_arrived_serial_ids = [(4, serial_identity.id)]
            # 到检即展开该样本 × 全部检验项的结果格（幂等，仅过站模式，
            # 已泛化到 oqc），默认全部合格，检验员只改异常格
            inspection._fai_expand_result_cells()
        else:
            # NG/报废：计入不良名单参与 d 与 Ac/Re 判定，样本名额
            # 刻意保持占用（FAI 在此剔除释放名额，OQC 不做）
            inspection.x_oqc_ng_serial_ids = [(4, serial_identity.id)]

    # ------------------------------------------------------------------
    # 报工模式数量收集器（决策 2）：首次合格报工建单（基数快照 0）、
    # 超额整笔拦（上限 = AQL 样本量 n）；NG/报废报工不占名额
    # ------------------------------------------------------------------
    def report_operation_qty(self, route_operation, qty_ok, qty_ng=0.0,
                             qty_scrap=0.0, scrap_reason=False):
        self.ensure_one()
        self._oqc_gate_report(route_operation, qty_ok)
        return super().report_operation_qty(
            route_operation, qty_ok, qty_ng=qty_ng, qty_scrap=qty_scrap,
            scrap_reason=scrap_reason)

    def _oqc_gate_report(self, route_operation, qty_ok):
        self.ensure_one()
        if self.x_manage_mode != 'report' or qty_ok <= 0:
            return  # 纯 NG/报废报工：调机记账，不占样本名额（同 FAI）
        inspection = self.x_oqc_inspection_id
        if not inspection:
            # 无单先建：报工模式同样触发（基数快照 0 = 从头累计），
            # 再按同一额度口径校验本笔
            inspection = self._oqc_maybe_open_round(route_operation)
        if not inspection or inspection._oqc_passed():
            return
        if route_operation.operation_id != inspection.scheme_id.operation_id:
            return  # 只拦 OQC 工序的报工
        remaining = inspection.sample_size - inspection.x_fai_reported_qty
        if qty_ok > remaining + 0.0001:
            raise ValidationError(_(
                'Outgoing inspection is in progress on MES order '
                '%(order)s: report at most %(remaining)s OK unit(s) in '
                'this batch.', order=self.name, remaining=max(remaining, 0.0)))

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
    """OQC 判定收口（oqc-entry-trigger 决策 3）：完检须样本齐套
    （到检 ∪ NG ≥ n）；判退不自动开新一轮——单据停在判退态、闸门
    保持，放行路径只有 action_reset_open 重开复检（再次完检按同一
    AQL 快照重判）或 action_mark_concession 让步整单放行（均现有
    方法，此处不动）。另把共享的样本计数闸门对齐到 OQC 的矩阵台账。"""

    _inherit = 'sn.wsd.quality.inspection'

    def _oqc_passed(self):
        """判定通过口径：state=done 且 result ∈ (pass, concession)。
        让步也算通过→整单放行；reject/fail/未完检都保持投入限流。"""
        self.ensure_one()
        return self.state == 'done' and self.result in ('pass', 'concession')

    def action_done(self):
        # OQC 过站矩阵：样本齐套才能完检——到检 ∪ NG 名单 ≥ 样本量 n
        # （NG 板同样计入到检口径：名额被占，d 由它们贡献）
        for inspection in self.filtered(
                lambda i: i.inspection_type == 'oqc' and i.state != 'done'
                and i.mes_order_id
                and i.mes_order_id.x_manage_mode != 'report'):
            arrived = len(inspection.x_fai_arrived_serial_ids
                          | inspection.x_oqc_ng_serial_ids)
            if arrived < inspection.sample_size:
                raise UserError(_(
                    'Outgoing inspection: only %(arrived)s of %(need)s '
                    'samples reached the outgoing operation; wait for the '
                    'full sample set.', arrived=arrived,
                    need=inspection.sample_size))
        # 判退不在此开新一轮（决策 3）：reject 联动（hold + 质量 issue
        # 转维修）由既有 _apply_quality_hold 在 super 链路内完成
        return super().action_done()

    def _apply_quality_hold(self):
        # 判退联动（任务 3.4）：既有口径只看缺陷行/Evidence SN，过站
        # 矩阵的不良 SN 在 NG 名单与 fail 格上——补齐 hold + issue，
        # 复用同一查重口径（同单同 SN 只开一张 issue）
        super()._apply_quality_hold()
        issue_model = self.env['sn.wsd.quality.issue']
        for inspection in self.filtered(
                lambda i: i._oqc_station_mode()
                and i.result in ('fail', 'reject')):
            default_defect_code = self.env['sn.wsd.quality.defect.code'].search([
                ('company_id', '=', inspection.company_id.id),
            ], order='severity desc, id asc', limit=1)
            for identity in inspection._oqc_bad_serial_ids():
                identity.x_quality_hold_state = 'hold'
                if default_defect_code and not issue_model.search([
                    ('serial_identity_id', '=', identity.id),
                    ('inspection_id', '=', inspection.id),
                ], limit=1):
                    issue_model.create({
                        'serial_identity_id': identity.id,
                        'route_operation_id': inspection.route_operation_id.id,
                        'workcenter_id': inspection.workcenter_id.id,
                        'defect_code_id': default_defect_code.id,
                        'issue_source': inspection.inspection_type,
                        'state': 'open',
                        'detected_time': fields.Datetime.now(),
                        'inspection_id': inspection.id,
                        'note': inspection.name,
                    })

    @api.depends(
        'inspection_type', 'mes_order_id.x_manage_mode',
        'sample_ids.result', 'sample_ids.serial_identity_id',
        'sample_ids.qty', 'sample_ids.defect_code_id', 'x_picked_qty',
        'x_fai_reported_qty',
        'x_fai_arrived_serial_ids', 'x_oqc_ng_serial_ids',
        'cell_ids.result', 'cell_ids.serial_identity_id',
    )
    def _compute_sample_counts(self):
        # OQC 建单时关了系统抽选（无预生成样本行）：把共享的
        # sample_checked_qty / sample_defect_qty 对齐到真实台账，让
        # sampling.py 的完检闸门（checked ≥ n）与展示读到 OQC 口径——
        # 过站 = 到检 ∪ NG 名单 / 不良 SN 去重；报工 = 已抽数量 /
        # 扫码落下的不良行（Ac/Re 判定的 d 在报工模式走 defect_qty
        # 缺陷行合计，由 sample_ids 为空时的既有回退路径承接）
        super()._compute_sample_counts()
        for inspection in self.filtered(
                lambda i: i.inspection_type == 'oqc' and i.mes_order_id):
            if inspection._oqc_station_mode():
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
