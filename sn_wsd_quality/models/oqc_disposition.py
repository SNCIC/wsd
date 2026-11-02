from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .oqc_disposition_event import (
    OQC_DISPOSITION_CLOSED_STATES,
    OQC_DISPOSITION_STATE_SELECTION,
)

# 每个处置动作要求的前置状态(None = 系统动作,不校验状态迁移;
# oqc-disposition-closure 决策 2 的状态机)
OQC_DISPOSITION_ACTION_STATES = {
    'baseline': None,
    'detected': None,
    'result_edit': None,
    'reopen': None,
    'full_close': None,
    'retest': ('pending', 'awaiting_reinspection'),
    'rework_start': ('pending',),
    'rework_arrive': ('reworking',),
    'rework_ng': ('reworking', 'awaiting_reinspection'),
    'scrap': ('pending', 'reworking', 'awaiting_reinspection'),
    'scrap_restore': ('scrapped',),
    'concession': ('pending',),
}

# 结案类动作:执行前必须有已确认的缺陷身份(未知原文码只允许登记)
OQC_DISPOSITION_CLOSURE_ACTIONS = ('retest', 'scrap', 'concession')

# 未结处置状态(决策 2):批次放行、完成闸门与批量捷径共同排除的口径
OQC_OPEN_DISPOSITION_STATES = ('pending', 'reworking', 'awaiting_reinspection')


class QualityInspectionDisposition(models.Model):
    """NG-board disposition actions on OQC inspections (oqc-ng-disposition):
    re-test = retype the cells, rework = pull the board back to an
    operation, scrap = native scrap + cells to N/A. No new documents."""

    _inherit = 'sn.wsd.quality.inspection'

    x_full_inspection = fields.Boolean(
        string='Full Lot Inspection', copy=False,
        help='Rejected-lot switch: the inspection reopens and the feeding '
             'gate lets every remaining board through the inspection '
             'operation one by one.')

    # ------------------------------------------------------------------
    # 处置审计事件（oqc-disposition-closure 决策 1/2 基础）
    # ------------------------------------------------------------------
    x_oqc_disposition_event_ids = fields.One2many(
        'sn.wsd.quality.oqc.disposition.event', 'inspection_id',
        string='OQC Disposition Events',
        help='Append-only audit trail of the NG-board dispositions taken '
             'on this inspection. Server-side pagination on the views; '
             'never load it in full.')
    x_oqc_pending_qty = fields.Integer(
        string='Awaiting Disposition', compute='_compute_x_oqc_disposition_counts',
        help='Known abnormal boards whose latest disposition event leaves '
             'them awaiting a decision (or with no event at all).')
    x_oqc_reworking_qty = fields.Integer(
        string='Reworking', compute='_compute_x_oqc_disposition_counts',
        help='Known abnormal boards currently walking an authorized '
             'rework route.')
    x_oqc_reinspection_qty = fields.Integer(
        string='Awaiting Re-inspection', compute='_compute_x_oqc_disposition_counts',
        help='Reworked boards back at the inspection operation whose '
             're-judgment is not confirmed yet.')
    x_oqc_release_ready = fields.Boolean(
        string='OQC Release Ready', compute='_compute_x_oqc_release_ready',
        help='True when the batch is done/pass or done/concession AND no '
             'known abnormal board is pending, reworking or awaiting '
             're-inspection.')
    x_oqc_release_message = fields.Char(
        string='OQC Release Message', compute='_compute_x_oqc_release_ready',
        help='First blocking reason when the batch is not release-ready.')

    # ------------------------------------------------------------------
    # 当前板集中处理区（oqc-disposition-closure 决策 5，任务 7.1/7.2）：
    # 全部非存储 compute，按读取时派生，不在板上存第二份状态
    # ------------------------------------------------------------------
    x_oqc_current_state = fields.Selection(
        OQC_DISPOSITION_STATE_SELECTION,
        string='Current Board Disposition',
        compute='_compute_x_oqc_current_state',
        help='Disposition state of the board currently shown in the '
             'inspection tab, derived from its latest disposition event.')
    x_oqc_current_state_info = fields.Char(
        string='Current Board Disposition Info',
        compute='_compute_x_oqc_current_state',
        help='One-line summary of the current board: state, defect code, '
             'rework attempts and freeze flag.')
    x_oqc_current_defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code', string='Current Board Defect Code',
        compute='_compute_x_oqc_current_state',
        help='Defect identity recorded on the current board\'s event chain.')
    x_oqc_current_rework_count = fields.Integer(
        string='Current Board Rework Count',
        related='x_fai_current_sn.x_rework_count',
        help='Rework attempts the current board has been through.')
    x_oqc_current_freeze_state = fields.Selection(
        related='x_fai_current_sn.x_freeze_state',
        string='Current Board Freeze State',
        help='Freeze flag of the current board; frozen boards refuse '
             'disposition actions.')
    x_oqc_disposition_event_count = fields.Integer(
        string='OQC Disposition Count',
        compute='_compute_x_oqc_disposition_event_count',
        help='Number of audit events on this inspection. Counted with a '
             'server-side search: the events themselves are never loaded '
             'into the form (paginated list only).')
    x_oqc_scrap_available = fields.Boolean(
        string='Scrap Disposition Available',
        compute='_compute_x_oqc_scrap_available',
        help='True when the scrap module (sn_wsd_scrap) is installed: the '
             'current-board scrap entry needs its scrap record flow. '
             'quality itself never depends on it.')
    x_oqc_scrap_hint = fields.Char(
        string='Scrap Disposition Hint',
        compute='_compute_x_oqc_scrap_available',
        help='Configuration hint shown instead of the scrap entry when the '
             'scrap module is missing.')

    @api.depends('x_oqc_disposition_event_ids', 'x_oqc_ng_serial_ids',
                 'cell_ids.result')
    def _compute_x_oqc_disposition_counts(self):
        for inspection in self:
            if not inspection._oqc_station_mode():
                inspection.x_oqc_pending_qty = 0
                inspection.x_oqc_reworking_qty = 0
                inspection.x_oqc_reinspection_qty = 0
                continue
            states = [info['state'] for info
                      in inspection._oqc_current_dispositions().values()]
            inspection.x_oqc_pending_qty = states.count('pending')
            inspection.x_oqc_reworking_qty = states.count('reworking')
            inspection.x_oqc_reinspection_qty = states.count(
                'awaiting_reinspection')

    @api.depends('state', 'result', 'x_oqc_disposition_event_ids',
                 'x_oqc_ng_serial_ids', 'cell_ids.result')
    def _compute_x_oqc_release_ready(self):
        for inspection in self:
            ready, message = inspection._oqc_release_status()
            inspection.x_oqc_release_ready = ready
            inspection.x_oqc_release_message = message

    @api.depends('inspection_type', 'mes_order_id.x_manage_mode',
                 'x_fai_current_sn', 'x_oqc_disposition_event_ids',
                 'x_oqc_ng_serial_ids', 'cell_ids.result')
    def _compute_x_oqc_current_state(self):
        # 当前板处理区（任务 7.2）：状态从 (检验单, 当前板) 最新事件派生，
        # 缺陷码取事件链最近一次有效登记；信息行拼接可读摘要
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        for inspection in self:
            serial = inspection.x_fai_current_sn
            if not serial or not inspection._oqc_station_mode():
                inspection.x_oqc_current_state = False
                inspection.x_oqc_current_state_info = False
                inspection.x_oqc_current_defect_code_id = False
                continue
            info = inspection._oqc_current_dispositions(
                serial).get(serial.id) or {}
            defect = Event.search([
                ('inspection_id', '=', inspection.id),
                ('serial_identity_id', '=', serial.id),
                ('defect_code_id', '!=', False),
            ], order='id desc', limit=1).defect_code_id
            inspection.x_oqc_current_state = info.get('state')
            inspection.x_oqc_current_defect_code_id = defect
            inspection.x_oqc_current_state_info = \
                inspection._oqc_current_board_summary(
                    serial, info.get('state'), defect)

    def _oqc_current_board_summary(self, serial, state, defect):
        """当前板信息行（任务 7.2）：状态 + 缺陷码 + 返工次数 + 冻结。"""
        self.ensure_one()
        labels = dict(OQC_DISPOSITION_STATE_SELECTION)
        parts = [labels.get(state) or _('No open disposition')]
        if defect:
            parts.append(defect.display_name)
        if serial.x_rework_count:
            parts.append(_('Rework attempts: %s', serial.x_rework_count))
        if serial.x_freeze_state == 'frozen':
            parts.append(_('Frozen'))
        return ' | '.join(parts)

    def _compute_x_oqc_disposition_event_count(self):
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        for inspection in self:
            inspection.x_oqc_disposition_event_count = Event.search_count([
                ('inspection_id', '=', inspection.id)])

    @api.depends()
    def _compute_x_oqc_scrap_available(self):
        # 软引用（任务 7.2）：quality 不依赖 sn_wsd_scrap——按钮可见性与
        # 提示按 env.get 探测，未安装时只显示配置提示，无可执行入口
        Scrap = self.env.get('sn.wsd.scrap.record')
        available = Scrap is not None
        for inspection in self:
            inspection.x_oqc_scrap_available = available
            inspection.x_oqc_scrap_hint = False if available else _(
                'Scrap disposal needs the scrap module (sn_wsd_scrap) '
                'installed; retest and rework work without it.')

    def _oqc_release_status(self):
        """统一释放条件（决策 2 基础部分）：done/pass 或 done/concession
        且无 pending/reworking/awaiting_reinspection。返回
        (ready, message)；message 为首要阻断原因。"""
        self.ensure_one()
        if not self._oqc_station_mode():
            return True, False
        if self.state != 'done':
            return False, _('The inspection is not completed.')
        if self.result not in ('pass', 'concession'):
            return False, _('Batch verdict: %s.',
                            self.result or 'pending')
        dispositions = self._oqc_current_dispositions()
        for state, label in (
                ('pending', 'awaiting disposition'),
                ('reworking', 'in rework'),
                ('awaiting_reinspection', 'awaiting re-inspection')):
            serial_ids = [sid for sid, info in dispositions.items()
                          if info['state'] == state]
            if serial_ids:
                names = self.env['sn.wsd.serial.identity'].browse(
                    serial_ids[:3]).mapped('name')
                return False, _(
                    '%s board(s) %s (e.g. %s).',
                    len(serial_ids), label, ', '.join(names))
        return True, False

    # ------------------------------------------------------------------
    # 服务方法（决策 2；后续批次的唯一入口，禁止旁路）
    # ------------------------------------------------------------------
    def _oqc_open_disposition_serials(self, states=None):
        """当前处置未结的板（决策 2，任务 2.2 口径）：按状态分组返回
        {state: serial recordset}。批次放行、action_done 完成闸门与
        全部合格捷径共用此口径，不再各自数名单/格子。"""
        self.ensure_one()
        states = states or OQC_OPEN_DISPOSITION_STATES
        Serial = self.env['sn.wsd.serial.identity']
        groups = {}
        for sid, info in self._oqc_current_dispositions().items():
            state = info.get('state')
            if state in states:
                groups.setdefault(state, Serial)
                groups[state] |= Serial.browse(sid)
        return groups

    def _oqc_open_disposition_summary(self, groups):
        """未结处置的可读摘要（任务 2.2）：供 UserError 提示列出 SN 与
        进度，如 "SN001 awaiting disposition, SN002 in rework"。"""
        labels = {
            'pending': 'awaiting disposition',
            'reworking': 'in rework',
            'awaiting_reinspection': 'awaiting re-inspection',
        }
        parts = []
        for state in OQC_OPEN_DISPOSITION_STATES:
            serials = groups.get(state)
            if serials:
                names = ', '.join(sorted(serials.mapped('name')))
                parts.append(
                    _('%s %s', names, labels.get(state, state)))
        return '; '.join(parts)

    def _oqc_released_except(self, serial_identity):
        """放行口径忽略指定板（任务 2.2 内部使用）：出站登记路径判断
        "本批在本次出站之前是否已放行"——正在登记的板自己的新 NG 事实
        不应把该判断翻掉（否则放行后的新 NG 会被早退吃掉）。"""
        self.ensure_one()
        for serials in self._oqc_open_disposition_serials().values():
            if serials - serial_identity:
                return False
        return True

    def _oqc_reopen_for_disposition(self):
        """done 单开始处置动作时调用（任务 2.2）：追加批次级 reopen 事件
        （serial 空；after_snapshot 记旧 result/state/finish_time），write
        state=open、finish_time=False。原 AQL 快照（sample_size/Ac/Re）不动，
        重新完成时按当前结果重判，过去结论由事件历史追溯。"""
        self.ensure_one()
        if not self._oqc_station_mode():
            raise UserError(_(
                'Disposition reopen applies to outgoing inspections of '
                'station-mode MES orders only.'))
        if self.state != 'done':
            return self
        self._oqc_lock()
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        token = Event.search([
            ('inspection_id', '=', self.id)], order='id desc', limit=1).id or 0
        previous = {
            'state': self.state,
            'result': self.result,
            'finish_time': fields.Datetime.to_string(self.finish_time)
            if self.finish_time else False,
        }
        self._oqc_append_events([{
            'action': 'reopen',
            'reason': 'Disposition started on a completed inspection; the '
                      'previous verdict is kept in this snapshot.',
            'before_snapshot': dict(self._oqc_batch_snapshot(), **previous),
            'after_snapshot': dict(
                self._oqc_batch_snapshot(), state='open',
                previous_state=previous['state'],
                previous_result=previous['result'],
                previous_finish_time=previous['finish_time']),
            'source_key': 'oqc-reopen-%s-%s' % (self.id, token),
        }])
        self.write({'state': 'open', 'finish_time': False})
        return self

    def _oqc_latest_oqc_history(self, serial_identity):
        """该板在本单 OQC 工序的最新过站行（任务 4.3）：判定"最近本站
        事实"是 NG 还是 OK，决定复测是否需要追加过站。"""
        self.ensure_one()
        order = self.mes_order_id
        scheme_op = self.scheme_id.operation_id
        if not order or not scheme_op:
            return self.env['sn.wsd.serial.operation.history']
        oqc_ops = order.x_mes_route_id.operation_ids.filtered(
            lambda r, op=scheme_op: r.operation_id == op)
        if not oqc_ops:
            return self.env['sn.wsd.serial.operation.history']
        return self.env['sn.wsd.serial.operation.history'].search([
            ('mes_order_id', '=', order.id),
            ('route_operation_id', 'in', oqc_ops.ids),
            ('serial_identity_id', '=', serial_identity.id),
            ('result', '!=', 'in_progress'),
        ], order='id desc', limit=1)

    def _oqc_action_retest(self, serial_identity, reason, cell_values,
                           defect_code_id=False):
        """就地复测收口（任务 4.2/4.3，决策 3）。

        只处理当前板：录入当次必检项目真实值（清除旧 manual fail 锁定
        后按值重判，超差不能被 pass 掩盖）。全部合格才结案；失败复测
        同样留事件、保持未结。若该板最近本站过站为 NG，先授予一次绑定
        本单/本 SN/本站/本次事件版本的复测授权（凭证字段承载，范围由
        x_rework_order_id/x_rework_operation_id 限定），通过共享
        pass_one_station 在同一事务追加本站 OK 履历（原 NG 保留）；
        最近本站已 OK（仅人工格异常）则不重复过站。全部失败整笔回滚。"""
        self.ensure_one()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_('Describe the retest reason.'))
        self._oqc_reopen_for_disposition()
        self._oqc_lock(serial_identity)
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        # 缺陷身份前置（结案校验要求事件链带有效缺陷码）
        if not Event.search_count([
                ('inspection_id', '=', self.id),
                ('serial_identity_id', '=', serial_identity.id),
                ('defect_code_id', '!=', False)]):
            if not defect_code_id:
                raise UserError(_(
                    'SN %(sn)s has no defect code yet; pick the defect '
                    'found on the board before confirming the retest.',
                    sn=serial_identity.name))
            self._oqc_append_events([{
                'serial_identity_id': serial_identity.id,
                'action': 'result_edit',
                'state_before': 'pending', 'state_after': 'pending',
                'reason': 'Defect identity recorded before retest closure.',
                'defect_code_id': defect_code_id,
                'source_key': 'oqc-defect-%s-%s-%s' % (
                    self.id, serial_identity.id,
                    (Event.search([
                        ('inspection_id', '=', self.id),
                        ('serial_identity_id', '=',
                         serial_identity.id)],
                        order='id desc', limit=1).id or 0)),
            }])
        # 版本令牌取缺陷补录之后的最新事件：它参与并发防重
        latest = Event.search([
            ('inspection_id', '=', self.id),
            ('serial_identity_id', '=', serial_identity.id)],
            order='id desc', limit=1)
        token = latest.id or 0
        dispositions = self._oqc_check_action(
            'retest', serial_identity,
            expected_versions={serial_identity.id: token})
        state_before = (dispositions.get(serial_identity.id) or {}
                        ).get('state') or 'pending'
        before_snapshot = dict(self._oqc_batch_snapshot(),
                               **self._oqc_cell_snapshot(serial_identity))
        # 写真实值：manual_result 归 pending 解除旧人工判定，按新值重判
        cells = self.cell_ids.filtered(
            lambda c: c.serial_identity_id == serial_identity)
        for line_id, vals in (cell_values or {}).items():
            cell = cells.filtered(lambda c, lid=line_id: c.line_id.id == lid)
            if cell:
                cell.with_context(
                    sn_wsd_oqc_cell_silent=True).write(vals)
        self.invalidate_recordset(['cell_ids'])
        cells = self.cell_ids.filtered(
            lambda c: c.serial_identity_id == serial_identity)
        failed_cells = cells.filtered(lambda c: c.result == 'fail')
        after_snapshot = dict(self._oqc_batch_snapshot(),
                              **self._oqc_cell_snapshot(serial_identity))
        event_vals = {
            'serial_identity_id': serial_identity.id,
            'action': 'retest',
            'state_before': state_before,
            'reason': reason,
            'defect_code_id': defect_code_id or False,
            'before_snapshot': before_snapshot,
            'after_snapshot': after_snapshot,
            'attempt_no': serial_identity.x_rework_count or 0,
            'source_key': 'oqc-retest-%s-%s-%s' % (
                self.id, serial_identity.id, token),
        }
        if failed_cells:
            # 失败复测（任务 4.2）：留事件、保持未结，可继续处理；
            # 不写 OK 履历，不改处置状态
            event_vals.update({
                'state_after': state_before
                if state_before in ('pending', 'awaiting_reinspection')
                else 'pending',
                'reason': _('Retest failed on %s. %s', ', '.join(
                    failed_cells.mapped('line_id.name')), reason),
            })
            self._oqc_append_events([event_vals])
            return False
        # 合格：最近本站 NG → 授权一次本站复测过站（同一事务追加 OK）
        order = self.mes_order_id
        oqc_row = order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == self.scheme_id.operation_id)[:1]
        history = self.env['sn.wsd.serial.operation.history']
        last_pass = self._oqc_latest_oqc_history(serial_identity)
        if last_pass and last_pass.result == 'ng':
            workcenter = last_pass.workcenter_id
            if not workcenter:
                workcenter = self.env['mrp.workcenter'].search([
                    ('x_operation_id', '=', self.scheme_id.operation_id.id),
                    ('x_production_line_id', '=',
                     order.production_line_id.id)], limit=1)
            serial_identity.x_rework_inspection_id = self.id
            serial_identity.x_rework_order_id = order.id
            serial_identity.x_rework_operation_id = oqc_row.id
            serial_identity.x_rework_started_at = fields.Datetime.now()
            serial_identity.x_rework_event_id_value = token
            order.with_context(sn_wsd_oqc_retest_pass=True).pass_one_station(
                serial_identity, workcenter, result='ok')
            serial_identity.x_rework_inspection_id = False
            history = self._oqc_latest_oqc_history(serial_identity)
        event_vals.update({
            'state_after': 'retest_passed',
            'history_id': history.id if history else False,
            'route_operation_id': oqc_row.id,
        })
        self._oqc_append_events([event_vals])
        # 重判通过 → 清凭证（任务 5.4）：返工授权在结案时失效；失败
        # 复测（上方 return False 分支）保留凭证与状态，可继续处理
        if serial_identity.x_rework_inspection_id == self.id:
            serial_identity.x_rework_inspection_id = False
            serial_identity.x_rework_operation_id = False
            serial_identity.x_rework_event_id_value = 0
        return True

    def _oqc_known_serials(self):
        """异常集合全集：原抽样名单 ∪ 本单已登记异常事件 SN ∪ fail 格
        SN ∪ NG 出站名单 ∪ 本单本站 NG/报废过站历史；全部过滤公司。
        资格校验（_oqc_check_action）与追加入口都以它为准。"""
        self.ensure_one()
        serials = self.x_fai_serial_ids | self.cell_ids.mapped(
            'serial_identity_id')
        serials |= self._oqc_disposition_universe()
        return serials.filtered(
            lambda s, company=self.company_id: s.company_id == company)

    def _oqc_ng_fact_serials(self):
        """仍有 NG 事实的板：NG/报废出站名单 ∪ 本单 OQC 工序的
        ng/scrap 过站行（按制令单 + 工序过滤）。"""
        self.ensure_one()
        serials = self.x_oqc_ng_serial_ids
        order = self.mes_order_id
        scheme_op = self.scheme_id.operation_id
        if order and scheme_op:
            oqc_ops = order.x_mes_route_id.operation_ids.filtered(
                lambda r, op=scheme_op: r.operation_id == op)
            if oqc_ops:
                serials |= self.env['sn.wsd.serial.operation.history']\
                    .search([
                        ('mes_order_id', '=', order.id),
                        ('route_operation_id', 'in', oqc_ops.ids),
                        ('result', 'in', ('ng', 'scrap')),
                    ]).mapped('serial_identity_id')
        return serials

    def _oqc_full_inspected_serials(self):
        """全检台账的已检集合（任务 3.3）：本单 OQC 工序存在终态过站行
        （ok/ng/scrap；in_progress 不算）的 SN 去重。重复复测、返工重走
        同一板不重复计台（「重复检验按板计数」）；与抽样名单无关——
        全检合格板不登名单，台账就是过站历史本身。"""
        self.ensure_one()
        order = self.mes_order_id
        scheme_op = self.scheme_id.operation_id
        if not order or not scheme_op:
            return self.env['sn.wsd.serial.identity']
        oqc_ops = order.x_mes_route_id.operation_ids.filtered(
            lambda r, op=scheme_op: r.operation_id == op)
        if not oqc_ops:
            return self.env['sn.wsd.serial.identity']
        return self.env['sn.wsd.serial.operation.history'].search([
            ('mes_order_id', '=', order.id),
            ('route_operation_id', 'in', oqc_ops.ids),
            ('result', '!=', 'in_progress'),
        ]).mapped('serial_identity_id')

    def _oqc_full_close_snapshot(self, inspected_qty, lot_qty, reason):
        """数量差异收口事件快照（任务 3.3）：记录实际已检数、批量、
        差异与理由——单据不宣称已检满批量。"""
        self.ensure_one()
        return {
            'inspected_qty': inspected_qty,
            'lot_qty': lot_qty,
            'gap_qty': max(lot_qty - inspected_qty, 0),
            'closure_reason': reason,
        }

    def _oqc_disposition_universe(self):
        """进入处置状态机的板：有异常事件、有 NG 事实或有 fail 格。
        普通样本/合格板不进——仅为异常板增加数据（Goals）。"""
        self.ensure_one()
        serials = self._oqc_ng_fact_serials()
        serials |= self.cell_ids.filtered(
            lambda c: c.result == 'fail').mapped('serial_identity_id')
        serials |= self.env['sn.wsd.quality.oqc.disposition.event'].search([
            ('inspection_id', '=', self.id),
            ('serial_identity_id', '!=', False),
        ]).mapped('serial_identity_id')
        return serials

    def _oqc_ensure_cells(self, serials):
        """为一组显式异常 SN 幂等铺格：复用 _fai_expand_result_cells 的
        铺格口径（样本 × 检验项、预填合格）但不把板加进抽样 m2m——
        全检新 NG 与名单内 NG 走同一条路径，合格板永不全量铺格。"""
        self.ensure_one()
        Cell = self.env['sn.wsd.quality.inspection.cell']
        for inspection in self:
            if not inspection._oqc_station_mode():
                raise UserError(_(
                    'Disposition cells apply to outgoing inspections of '
                    'station-mode MES orders only.'))
            existing = {
                (cell.serial_identity_id.id, cell.line_id.id)
                for cell in inspection.cell_ids}
            cell_values = [
                {
                    'inspection_id': inspection.id,
                    'company_id': inspection.company_id.id,
                    'serial_identity_id': serial.id,
                    'line_id': line.id,
                }
                for serial in serials
                for line in inspection.line_ids
                if (serial.id, line.id) not in existing]
            if cell_values:
                cells = Cell.create(cell_values)
                # 预填合格同矩阵展开口径；静音通用格钩子（程序化铺格
                # 不是人工编辑，detected 由调用路径自己记录）
                cells.with_context(
                    sn_wsd_oqc_cell_silent=True)._set_pass_values()
        return True

    def _oqc_current_dispositions(self, serials=None):
        """按 (检验单, SN) 批量取最新事件得当前处置状态。

        保守口径（「无结果格不能自动销项」）：存在 NG 事实却无事件或
        无格的板一律 pending，不得视为合格。返回
        {serial_id: {'state': ..., 'event_id': ...}}；普通板（无事件且
        不在异常全集）不出现。"""
        self.ensure_one()
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        domain = [('inspection_id', '=', self.id),
                  ('serial_identity_id', '!=', False)]
        if serials is not None:
            domain.append(('serial_identity_id', 'in', serials.ids))
        latest = {}
        for event in Event.search(domain, order='id asc'):
            latest[event.serial_identity_id.id] = event
        universe = self._oqc_disposition_universe()
        ng_fact_ids = set(self._oqc_ng_fact_serials().ids)
        cell_serial_ids = set(
            self.cell_ids.mapped('serial_identity_id').ids)
        dispositions = {}
        for serial in (serials if serials is not None else universe):
            event = latest.get(serial.id)
            if not event and serial not in universe:
                continue  # 普通板：无处置状态可报
            if event and event.state_after:
                # 保守口径只降级"格背书"的结案：retest_passed 需要
                # 实测格证据；scrapped/concession 由报废单/让步决策
                # 背书，缺格不否定结案
                if serial.id in ng_fact_ids \
                        and serial.id not in cell_serial_ids \
                        and event.state_after not in ('scrapped',
                                                      'concession'):
                    state = 'pending'
                else:
                    state = event.state_after
            else:
                state = 'pending'
            dispositions[serial.id] = {
                'state': state, 'event_id': event.id if event else False}
        return dispositions

    def _oqc_check_action(self, action, serials, expected_versions=None):
        """统一资格校验（决策 2）：来源合法、状态匹配、缺陷码齐全、
        冻结/报废拦截与并发版本。expected_versions = {serial_id:
        event_id}（页面加载时的最新事件）；落后于最新事件即拒绝。
        校验通过返回当前处置映射，失败抛 UserError。"""
        self.ensure_one()
        if not self._oqc_station_mode():
            raise UserError(_(
                'Disposition actions apply to outgoing inspections of '
                'station-mode MES orders only.'))
        if action not in OQC_DISPOSITION_ACTION_STATES:
            raise UserError(_('Unknown disposition action "%s".', action))
        known = self._oqc_known_serials()
        unknown = serials - known
        if unknown:
            raise UserError(_(
                'SN %s is not part of inspection %s.',
                ', '.join(sorted(unknown.mapped('name'))), self.name))
        dispositions = self._oqc_current_dispositions(serials)
        if expected_versions is not None:
            for serial in serials:
                expected = expected_versions.get(serial.id)
                current_id = dispositions.get(serial.id, {}).get('event_id')
                if expected != current_id:
                    raise UserError(_(
                        'The disposition of SN %s changed since it was '
                        'loaded; refresh the board and retry.',
                        serial.name))
        required_states = OQC_DISPOSITION_ACTION_STATES[action]
        for serial in serials:
            info = dispositions.get(serial.id) or {}
            state = info.get('state')
            if state == 'scrapped' and action != 'scrap_restore':
                raise UserError(_(
                    'SN %s is scrapped; only a scrap restore can touch it '
                    'again.', serial.name))
            if required_states and state not in required_states:
                raise UserError(_(
                    'SN %s is currently "%s"; action "%s" requires %s.',
                    serial.name, state or 'no disposition', action,
                    ' / '.join(required_states)))
            if action != 'scrap_restore' \
                    and serial.x_freeze_state == 'frozen':
                freeze = serial.active_freeze_id
                raise UserError(_(
                    'SN %s is frozen%s; release the freeze before '
                    'disposition actions.', serial.name,
                    ' (%s)' % freeze.name if freeze else ''))
            if action in OQC_DISPOSITION_CLOSURE_ACTIONS \
                    and not self.env['sn.wsd.quality.oqc.disposition.event']\
                    .search_count([
                        ('inspection_id', '=', self.id),
                        ('serial_identity_id', '=', serial.id),
                        ('defect_code_id', '!=', False)]):
                raise UserError(_(
                    'SN %s has no defect code yet; record a valid defect '
                    'code before closing its disposition.', serial.name))
        return dispositions

    def _oqc_append_events(self, vals_list):
        """唯一私有追加入口（决策 6）：完成公司/单据写权限/SN 归属检查
        后以最小 sudo 创建。operator/event_time 在 sudo 前由服务端捕获
        （客户端不可冒填）；超级用户显式提供的值（升级基线）除外。
        同值保存不制造重复事件由调用侧判断。"""
        self.ensure_one()
        self.check_access_rights('write')
        self.check_access_rule('write')
        operator = self.env.user
        now = fields.Datetime.now()
        known = self._oqc_known_serials()
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            company_id = vals.get('company_id') or self.company_id.id
            if company_id != self.company_id.id:
                raise UserError(_(
                    'Disposition events must carry the company of their '
                    'inspection.'))
            vals['company_id'] = self.company_id.id
            vals['inspection_id'] = self.id
            vals['mes_order_id'] = self.mes_order_id.id
            serial = vals.get('serial_identity_id')
            if serial:
                serial_id = serial.id if hasattr(serial, 'id') else int(serial)
                if serial_id not in known.ids:
                    raise UserError(_(
                        'SN %s is not part of inspection %s.',
                        self.env['sn.wsd.serial.identity'].browse(
                            serial_id).name, self.name))
            if not (self.env.su and vals.get('operator_id')):
                vals['operator_id'] = operator.id
            if not (self.env.su and vals.get('event_time')):
                vals['event_time'] = now
            prepared.append(vals)
        return Event.sudo().with_context(
            sn_wsd_oqc_event_internal=True).create(prepared)

    def _oqc_lock(self, serials=False):
        """共享加锁序列（决策 6）：先 FOR UPDATE 检验单行，再按 SN id
        升序 FOR UPDATE serial.identity 行。所有确认入口（复测/返工/
        报废/让步/完成/入库）必须按同一顺序加锁，锁内复读最新事件。"""
        self.ensure_one()
        self.env.cr.execute(
            'SELECT id FROM sn_wsd_quality_inspection '
            'WHERE id = %s FOR UPDATE', [self.id])
        serial_ids = sorted({serial.id for serial in (serials or [])})
        if serial_ids:
            self.env.cr.execute(
                'SELECT id FROM sn_wsd_serial_identity '
                'WHERE id IN %s ORDER BY id FOR UPDATE',
                [tuple(serial_ids)])
        return True

    # ------------------------------------------------------------------
    # 审计事件构造助手
    # ------------------------------------------------------------------
    def _oqc_batch_snapshot(self):
        self.ensure_one()
        return {
            'inspection': self.name,
            'state': self.state,
            'result': self.result,
            'sample_size': self.sample_size,
            'accept_qty': self.accept_qty,
            'reject_qty': self.reject_qty,
            'full_inspection': bool(self.x_full_inspection),
        }

    def _oqc_cell_snapshot(self, serial):
        self.ensure_one()
        cells = self.cell_ids.filtered(
            lambda c, sn=serial: c.serial_identity_id == sn)
        return {'cells': [cell._oqc_event_cell_snapshot() for cell
                          in cells.sorted(
                              key=lambda c: (c.line_id.sequence or 0,
                                             c.line_id.id))]}

    def _oqc_log_detected_from_history(self, serial_identity,
                                       route_operation):
        """设备/过站 NG 落 detected 事件（任务 1.4）：source_key 采用
        过站历史身份，设备重发不重复追加；history_id 落 m2o。"""
        self.ensure_one()
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        History = self.env['sn.wsd.serial.operation.history']
        history = History.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.mes_order_id.id),
            ('route_operation_id', '=', route_operation.id),
            ('result', 'in', ('ng', 'scrap')),
        ], order='id desc', limit=1)
        history_ref = history.id if history else False
        source_key = 'oqc-detected-%s-%s-%s' % (
            self.mes_order_id.id, serial_identity.id,
            history_ref or fields.Datetime.now().strftime(
                '%Y%m%d%H%M%S%f'))
        if Event.search_count([
                ('company_id', '=', self.company_id.id),
                ('source_key', '=', source_key)]):
            return Event.browse()  # 设备重发：同历史身份不重复追加
        info = self._oqc_current_dispositions(
            serial_identity).get(serial_identity.id) or {}
        # state_before 只认真实事件：无事件 = 从未进入处置
        state_before = info['state'] if info.get('event_id') else False
        return self._oqc_append_events([{
            'serial_identity_id': serial_identity.id,
            'action': 'detected',
            'state_before': state_before,
            'state_after': 'pending',
            'attempt_no': serial_identity.x_rework_count or 0,
            'reason': 'Station NG reported at operation %s.'
                      % route_operation.display_label,
            'defect_code_id': history.defect_code_id.id if history else False,
            'defect_code_raw': self.env.context.get(
                'sn_wsd_oqc_defect_raw') or False,
            'before_snapshot': dict(
                self._oqc_batch_snapshot(), source='station_ng'),
            'after_snapshot': dict(self._oqc_batch_snapshot(),
                                   **self._oqc_cell_snapshot(serial_identity)),
            'route_operation_id': route_operation.id,
            'history_id': history_ref,
            'source_key': source_key,
        }])

    def _oqc_log_cell_edit_events(self, cells, before):
        """人工格提交差异（任务 1.5）：值有实际变化时按 (检验单, SN)
        落一条事件——新 fail 且当前无未结处置 → detected（重新进入
        pending）；已进入处置的板 → result_edit（前后状态相同，不改
        进度）；普通合格板的编辑不产生事件（仅为异常板增加数据）。"""
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        for inspection in self:
            insp_cells = cells.filtered(
                lambda c, i=inspection: c.inspection_id == i)
            current = inspection._oqc_current_dispositions(
                insp_cells.mapped('serial_identity_id'))
            for serial in insp_cells.mapped('serial_identity_id'):
                sn_cells = insp_cells.filtered(
                    lambda c, sn=serial: c.serial_identity_id == sn)
                changed = sn_cells.filtered(
                    lambda c: before.get(c.id) != c._oqc_event_cell_snapshot())
                if not changed:
                    continue  # 同值保存不制造事件
                info = current.get(serial.id) or {}
                state = info.get('state')
                has_event = bool(info.get('event_id'))
                has_fail = any(
                    cell.result == 'fail' for cell
                    in inspection.cell_ids.filtered(
                        lambda c, sn=serial: c.serial_identity_id == sn))
                defect = next((cell.defect_code_id for cell in changed
                               if cell.defect_code_id), False)
                base = {
                    'serial_identity_id': serial.id,
                    'attempt_no': serial.x_rework_count or 0,
                    'defect_code_id': defect.id if defect else False,
                    'route_operation_id': inspection.route_operation_id.id,
                }
                if has_fail and (not has_event
                                 or state in OQC_DISPOSITION_CLOSED_STATES):
                    inspection._oqc_append_events([dict(base, **{
                        'action': 'detected',
                        'state_before': state if has_event else False,
                        'state_after': 'pending',
                        'reason': 'Failing result submitted on the '
                                  'inspection cells.',
                        'before_snapshot': dict(
                            inspection._oqc_batch_snapshot(),
                            source='cell_fail'),
                        'after_snapshot': dict(
                            inspection._oqc_batch_snapshot(),
                            **inspection._oqc_cell_snapshot(serial)),
                        'source_key': 'oqc-cell-detected-%s-%s-%s' % (
                            inspection.id, serial.id,
                            info.get('event_id') or 0),
                    })])
                elif state:
                    inspection._oqc_append_events([dict(base, **{
                        'action': 'result_edit',
                        'state_before': state,
                        'state_after': state,
                        'reason': 'Inspection cell values edited.',
                        'before_snapshot': {
                            'cells': [before[cell.id] for cell in changed]},
                        'after_snapshot': {
                            'cells': [cell._oqc_event_cell_snapshot()
                                      for cell in changed]},
                        'source_key': 'oqc-result-edit-%s-%s-%s' % (
                            inspection.id, serial.id,
                            info.get('event_id') or 0),
                    })])
        return True

    # ------------------------------------------------------------------
    # 升级基线（决策 6,任务 1.5）：迁移脚本与测试共用的导入函数
    # ------------------------------------------------------------------
    def _oqc_build_baseline(self):
        """按可见证据给存量 OQC 过站单的已知异常板一次性建 baseline
        事件。证据优先级：已确认报废 > 活跃返工凭证 > 充分复测通过
        证据（有格、格无 fail、在到检名单）> 其余 NG 事实 pending。
        不补造历史测量值/时间/操作人；operator 固定系统用户（本构建
        无 OdooBot，用 base.user_root/__system__），时间为迁移时刻；
        幂等（已有事件的板跳过）。"""
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        History = self.env['sn.wsd.serial.operation.history']
        bot = self.env.ref('base.user_root')
        now = fields.Datetime.now()
        created = Event
        for inspection in self.filtered(
                lambda i: i._oqc_station_mode()):
            covered = set(Event.search([
                ('inspection_id', '=', inspection.id),
                ('serial_identity_id', '!=', False),
            ]).mapped('serial_identity_id').ids)
            ng_facts = inspection._oqc_ng_fact_serials()
            fail_cells = inspection.cell_ids.filtered(
                lambda c: c.result == 'fail').mapped('serial_identity_id')
            universe = ng_facts | fail_cells
            order = inspection.mes_order_id
            # 活跃返工凭证：本单发放且尚未关闭
            voucher = self.env['sn.wsd.serial.identity'].search([
                ('x_rework_inspection_id', '=', inspection.id)])
            universe |= voucher
            # 已确认报废（仅当 scrap 模块在场：quality 不反向依赖，
            # 快照 json 存来源 id，真实 m2o 由 sn_wsd_scrap 扩展声明）
            scrap_map = {}
            if 'sn.wsd.scrap.record' in self.env:
                for record in self.env['sn.wsd.scrap.record'].search([
                        ('mes_order_id', '=', order.id),
                        ('state', '=', 'scrapped')]):
                    scrap_map[record.serial_identity_id.id] = record
                universe |= self.env['sn.wsd.serial.identity'].browse(
                    scrap_map.keys())
            universe = universe.filtered(
                lambda s, company=inspection.company_id:
                    s.company_id == company)
            arrived_ids = set(inspection.x_fai_arrived_serial_ids.ids)
            cell_serial_ids = set(
                inspection.cell_ids.mapped('serial_identity_id').ids)
            fail_ids = set(fail_cells.ids)
            voucher_ids = set(voucher.ids)
            scheme_op = inspection.scheme_id.operation_id
            oqc_ops = order.x_mes_route_id.operation_ids.filtered(
                lambda r, op=scheme_op: r.operation_id == op
            ) if scheme_op else order.x_mes_route_id.operation_ids
            vals_list = []
            for serial in universe.sorted(key=lambda s: s.id):
                if serial.id in covered:
                    continue
                ng_domain = [
                    ('serial_identity_id', '=', serial.id),
                    ('mes_order_id', '=', order.id),
                    ('result', 'in', ('ng', 'scrap')),
                ]
                if oqc_ops:
                    ng_domain.append(('route_operation_id', 'in', oqc_ops.ids))
                latest_ng = History.search(ng_domain, order='id desc',
                                           limit=1)
                defect = latest_ng.defect_code_id or next(
                    (cell.defect_code_id for cell in inspection.cell_ids
                     if cell.serial_identity_id == serial
                     and cell.defect_code_id), False)
                if serial.id in scrap_map:
                    state, evidence = 'scrapped', 'confirmed scrap record'
                elif serial.id in voucher_ids:
                    state, evidence = 'reworking', 'active rework voucher'
                elif (serial.id in arrived_ids
                        and serial.id in cell_serial_ids
                        and serial.id not in fail_ids):
                    state, evidence = 'retest_passed', (
                        'arrived with no failing cell')
                else:
                    state, evidence = 'pending', (
                        'visible NG fact without closure evidence')
                vals_list.append({
                    'serial_identity_id': serial.id,
                    'action': 'baseline',
                    'state_before': False,
                    'state_after': state,
                    'attempt_no': serial.x_rework_count or 0,
                    'reason': 'Upgrade baseline from visible evidence',
                    'defect_code_id': defect.id if defect else False,
                    'before_snapshot': dict(
                        inspection._oqc_batch_snapshot(),
                        evidence=evidence,
                        in_ng_list=serial.id in set(ng_facts.ids),
                        has_fail_cell=serial.id in fail_ids,
                        scrap_record_id=(
                            scrap_map[serial.id].id
                            if serial.id in scrap_map else False),
                    ),
                    'after_snapshot': {'state': state},
                    'operator_id': bot.id,
                    'event_time': now,
                    'history_id': latest_ng.id if latest_ng else False,
                    'source_key': 'oqc-baseline-%s-%s' % (
                        inspection.id, serial.id),
                })
            if vals_list:
                created |= inspection.sudo()._oqc_append_events(vals_list)
        return created

    # ------------------------------------------------------------------
    # 当前板处理区入口 + 服务端分页台账（任务 7.1-7.3，决策 5）
    # ------------------------------------------------------------------
    def _oqc_panel_guard(self):
        """公共 RPC 方法（oqc_current_board_info / oqc_ledger_page）的前置
        守卫：过站矩阵单 + 公司边界；跨公司单据与单内数据同等拒绝，不泄露
        对方存在与否。"""
        if not self or not self.exists() or not self._oqc_station_mode():
            raise UserError(_(
                'The current-board panel applies to outgoing inspections of '
                'station-mode MES orders only.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_(
                'You are not allowed to access this inspection.'))
        return self

    @api.model
    def oqc_current_board_info(self, inspection_id, serial_name):
        """当前板资格 + 进度（任务 7.1，决策 5）：供处理区/扫码联动读取。

        合法 = 本单原抽样板 ∪ 已登记异常板（_oqc_known_serials，含公司
        过滤）。非法 SN（其他制令单、未登记非样本、跨公司、不存在）一律
        同一句拒绝文案——不泄露跨公司信息；本方法只读，不改当前选择。"""
        inspection = self.browse(inspection_id)._oqc_panel_guard()
        serial_name = (serial_name or '').strip()
        if not serial_name:
            raise UserError(_('Scan or pick a board first.'))
        serial = self.env['sn.wsd.serial.identity'].search([
            ('name', '=', serial_name),
            ('company_id', '=', inspection.company_id.id)], limit=1)
        if not serial or serial not in inspection._oqc_known_serials():
            raise UserError(_(
                'SN %s is not part of inspection %s.',
                serial_name, inspection.name))
        info = inspection._oqc_current_dispositions(
            serial).get(serial.id) or {}
        defect = self.env['sn.wsd.quality.oqc.disposition.event'].search([
            ('inspection_id', '=', inspection.id),
            ('serial_identity_id', '=', serial.id),
            ('defect_code_id', '!=', False),
        ], order='id desc', limit=1).defect_code_id
        return {
            'serial_id': serial.id,
            'serial_name': serial.name,
            'state': info.get('state') or False,
            'event_id': info.get('event_id') or False,
            'defect_code_id': defect.id,
            'defect_code_name': defect.display_name if defect else False,
            'rework_count': serial.x_rework_count or 0,
            'freeze_state': serial.x_freeze_state,
            'state_info': inspection._oqc_current_board_summary(
                serial, info.get('state'), defect),
        }

    def _oqc_ledger_verdict(self, state, station_result):
        """台账最终判定（任务 7.1）：处置状态覆盖原始过站结果——复测
        合格板退出不良口径、报废板计报废、未结处置保持不良；普通板回退
        到最近一次过站终态。筛选与计数共用此口径。"""
        if state == 'scrapped':
            return 'scrap'
        if state in OQC_OPEN_DISPOSITION_STATES:
            return 'ng'
        if state == 'retest_passed':
            return 'retested'
        if state == 'concession':
            return 'concession'
        return {'ok': 'ok', 'ng': 'ng', 'scrap': 'scrap'}.get(
            station_result, 'ok')

    @api.model
    def oqc_ledger_page(self, inspection_id, filter='all', page=1,
                        page_size=80, search=''):
        """已检清单分页查询（任务 7.1/7.3，决策 5）。

        顺序固定：先按 SN 取最新终态过站行（DISTINCT ON，服务端聚合，
        不把全量格/事件发给浏览器），再叠加处置状态得出最终判定，
        然后按判定筛选、计数、分页；事件链缺陷码只查本页 SN。
        重复过站按 SN 计 1（最新行即当前结果）。"""
        inspection = self.browse(inspection_id)._oqc_panel_guard()
        filter = filter if filter in ('all', 'ok', 'ng', 'scrap') else 'all'
        try:
            page = max(1, int(page or 1))
            page_size = max(1, min(200, int(page_size or 80)))
        except (TypeError, ValueError):
            page, page_size = 1, 80
        result = {
            'total': 0, 'page': page, 'page_count': 1, 'page_size': page_size,
            'counts': {'ok': 0, 'ng': 0, 'scrap': 0}, 'rows': [],
        }
        order = inspection.mes_order_id
        scheme_op = inspection.scheme_id.operation_id
        oqc_ops = order.x_mes_route_id.operation_ids.filtered(
            lambda r, op=scheme_op: r.operation_id == op)
        if not oqc_ops:
            return result
        self.env.cr.execute("""
            SELECT DISTINCT ON (h.serial_identity_id)
                   h.serial_identity_id AS serial_id, h.id AS history_id,
                   h.result, h.out_date, h.operator_code, h.defect_code_id
              FROM sn_wsd_serial_operation_history h
             WHERE h.mes_order_id = %s
               AND h.route_operation_id IN %s
               AND h.result != 'in_progress'
             ORDER BY h.serial_identity_id, h.id DESC
        """, [order.id, tuple(oqc_ops.ids)])
        latest = self.env.cr.dictfetchall()
        Serial = self.env['sn.wsd.serial.identity']
        names = {serial.id: serial.name for serial in Serial.browse(
            [row['serial_id'] for row in latest])}
        search = (search or '').strip().lower()
        if search:
            latest = [row for row in latest if search in (
                names.get(row['serial_id']) or '').lower()]
        # 处置状态只在异常全集上派生（事件只为异常板而写），与批量大无关
        dispositions = inspection._oqc_current_dispositions()
        entries = []
        for row in latest:
            state = (dispositions.get(row['serial_id']) or {}).get('state')
            verdict = inspection._oqc_ledger_verdict(state, row['result'])
            if verdict in ('retested', 'concession'):
                result['counts']['ok'] += 1
            elif verdict in result['counts']:
                result['counts'][verdict] += 1
            entries.append((row, verdict, state))
        entries.sort(key=lambda item: item[0]['history_id'], reverse=True)
        if filter != 'all':
            keep = {'ok': ('ok', 'retested', 'concession'),
                    'ng': ('ng',), 'scrap': ('scrap',)}[filter]
            entries = [item for item in entries if item[1] in keep]
        result['total'] = len(entries)
        result['page_count'] = max(1, -(-result['total'] // page_size))
        result['page'] = min(page, result['page_count'])
        page_entries = entries[
            (result['page'] - 1) * page_size:result['page'] * page_size]
        # 事件链缺陷码：仅本页 SN（任务 7.1 关键约束）
        page_serial_ids = [item[0]['serial_id'] for item in page_entries]
        chain_defects = {}
        if page_serial_ids:
            for event in self.env[
                    'sn.wsd.quality.oqc.disposition.event'].search([
                        ('inspection_id', '=', inspection.id),
                        ('serial_identity_id', 'in', page_serial_ids),
                        ('defect_code_id', '!=', False)], order='id asc'):
                chain_defects[event.serial_identity_id.id] = \
                    event.defect_code_id.display_name
        Defect = self.env['sn.wsd.quality.defect.code']
        for row, verdict, state in page_entries:
            defect = chain_defects.get(row['serial_id'])
            if not defect and row['defect_code_id']:
                defect = Defect.browse(row['defect_code_id']).display_name
            result['rows'].append({
                'serial_id': row['serial_id'],
                'serial_name': names.get(row['serial_id']),
                'verdict': verdict,
                'station_result': row['result'],
                'disposition_state': state or False,
                'out_date': fields.Datetime.to_string(row['out_date'])
                if row['out_date'] else False,
                'operator_code': row['operator_code'] or '',
                'defect_code': defect or '',
                'history_id': row['history_id'],
            })
        return result

    def _oqc_current_sn_or_error(self):
        """处理区按钮共用的当前板前置检查（任务 7.2）：资格仍由各向导/服务
        提交侧重算校验，这里只拦"没有当前板"的明显误点。"""
        self.ensure_one()
        if not self._oqc_station_mode():
            raise UserError(_(
                'The current-board panel applies to outgoing inspections of '
                'station-mode MES orders only.'))
        serial = self.x_fai_current_sn
        if not serial:
            raise UserError(_(
                'Scan or pick a board first: the disposition actions work on '
                'the current board.'))
        return serial

    def action_oqc_retest_current_sn(self):
        """处理区入口：确认复测（任务 7.2）——开复测向导预填当前板。"""
        serial = self._oqc_current_sn_or_error()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Confirm Board Retest'),
            'res_model': 'sn.wsd.quality.oqc.retest.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_inspection_id': self.id,
                'default_serial_identity_id': serial.id,
            },
        }

    def action_oqc_rework_current_sn(self):
        """处理区入口：退回返工（任务 7.2）——开返工向导预填当前板。"""
        serial = self._oqc_current_sn_or_error()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rework Decision'),
            'res_model': 'sn.wsd.quality.oqc.rework.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_inspection_id': self.id,
                'default_serial_ids': [(6, 0, serial.ids)],
            },
        }

    def action_oqc_scrap_current_sn(self):
        """处理区入口：报废（任务 7.2）——跳既有 sn.wsd.scrap.record 新建，
        default context 预填 serial/production/mes_order/route_operation；
        quality 不依赖 scrap（按钮可见性由 x_oqc_scrap_available 决定，
        这里再拦一次直调）。"""
        Scrap = self.env.get('sn.wsd.scrap.record')
        if Scrap is None:
            raise UserError(_(
                'Scrap disposal needs the scrap module (sn_wsd_scrap) '
                'installed; retest and rework work without it.'))
        serial = self._oqc_current_sn_or_error()
        order = self.mes_order_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Scrap Record'),
            'res_model': 'sn.wsd.scrap.record',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_serial_identity_id': serial.id,
                'default_production_id': order.production_id.id,
                'default_mes_order_id': order.id,
                'default_route_operation_id': self.route_operation_id.id,
                'default_scrap_qty': 1.0,
            },
        }

    def action_open_oqc_disposition_events(self):
        """处置历史入口（任务 7.3）：标准 act_window 列表按本单过滤、
        服务端分页；表单不嵌 one2many 全量加载事件。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OQC Disposition History'),
            'res_model': 'sn.wsd.quality.oqc.disposition.event',
            'view_mode': 'list',
            'domain': [('inspection_id', '=', self.id)],
            'context': {'default_inspection_id': self.id},
        }

    # ------------------------------------------------------------------
    # Rework: pull an NG sample board back to a production operation
    # ------------------------------------------------------------------
    def _oqc_rework_target_candidates(self):
        """合法返工目标 = 本单 OQC 工序的图祖先（任务 5.2）：沿路线边
        blocked_by_ids BFS 上溯，排除 OQC 本站、下游工序与不连通分支；
        按图边判定，不按 sequence 大小猜测。"""
        self.ensure_one()
        order = self.mes_order_id
        scheme_op = self.scheme_id.operation_id
        empty = self.env['sn.wsd.mes.order.route.operation']
        if not order or not scheme_op:
            return empty
        oqc_rows = order.x_mes_route_id.operation_ids.filtered(
            lambda r, op=scheme_op: r.operation_id == op)
        if not oqc_rows:
            return empty
        ancestors = empty
        frontier = oqc_rows.mapped('blocked_by_ids')
        visited = set()
        while frontier:
            ancestors |= frontier
            visited |= set(frontier.ids)
            frontier = frontier.mapped('blocked_by_ids').filtered(
                lambda r, seen=visited: r.id not in seen)
        return ancestors

    def _oqc_serial_already_received(self, serial_identity):
        """该板是否已实际入库（任务 5.2）：台级 lot 出现在已过账的本单
        完工收货明细，或其包装记录所在托盘已收货/发货。已入库的板拒绝
        返工，提示走既有库存纠正流程。"""
        self.ensure_one()
        order = self.mes_order_id
        if not order:
            return False
        warehouse = order.production_id.picking_type_id.warehouse_id
        if warehouse and warehouse.picking_type_receipt_id:
            receipts = order.picking_ids.filtered(
                lambda p: p.state == 'done'
                and p.picking_type_id == warehouse.picking_type_receipt_id)
            lot_names = receipts.move_ids.move_line_ids.lot_id.mapped('name')
            if lot_names and serial_identity.name in lot_names:
                return True
        # 包装侧：板的包装记录挂的托盘已收货/已发货
        packs = self.env['sn.wsd.meter.pack.record'].search([
            ('serial_identity_id', '=', serial_identity.id)])
        pallet_names = set()
        for carton in packs.mapped('carton_package_id'):
            for log in self.env['sn.wsd.carton.pallet.binding.log'].search([
                    ('carton_package_id', '=', carton.id)]):
                pallet_names.add(log.pallet_package_id.name)
        if pallet_names:
            received = self.env['stock.package'].search([
                ('name', 'in', list(pallet_names)),
                ('x_wsd_pack_state', 'in', ('received', 'shipped'))])
            return bool(received)
        return False

    def action_rework_sn(self, serial_identity, route_operation, reason):
        """Arm a scoped rework voucher for one board (task 5.2, decision 3).

        The target must be a graph ancestor of the inspection operation.
        Starting rework only creates the voucher group and the audit event:
        the board waits for a real scan at the target station (no WIP or
        history row is fabricated here, no old row is deleted); progress
        counts only OK rows newer than the voucher's start time. Back at
        the inspection operation the board turns awaiting-reinspection;
        the explicit retest confirmation clears the voucher."""
        self.ensure_one()
        if self.inspection_type != 'oqc' or not self.mes_order_id \
                or self.mes_order_id.x_manage_mode == 'report':
            raise UserError(_(
                'Rework applies to outgoing inspections of station-mode '
                'MES orders only.'))
        if not (reason or '').strip():
            raise ValidationError(_('Describe the rework reason.'))
        order = self.mes_order_id
        self._oqc_reopen_for_disposition()
        self._oqc_lock(serial_identity)
        # 资格（来源/状态/冻结/报废/缺陷码链）统一走服务校验
        self._oqc_check_action('rework_start', serial_identity)
        if route_operation.mes_order_id != order:
            raise ValidationError(_(
                'The rework operation must belong to MES order %s.',
                order.name))
        candidates = self._oqc_rework_target_candidates()
        if route_operation not in candidates:
            raise ValidationError(_(
                'Operation %(op)s is not an upstream ancestor of the '
                'outgoing inspection operation: pick one of %(candidates)s.',
                op=route_operation.display_label,
                candidates=', '.join(candidates.mapped('display_label'))
                or '-'))
        Wip = self.env['sn.wsd.serial.wip']
        wip = Wip.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', order.id),
        ], limit=1)
        if wip:
            # 活动在制不允许直接拨回（任务 5.2）：先在所在站完成正常
            # 判定（OK/NG/报废），不遗留悬空 in_progress
            raise ValidationError(_(
                'SN %(sn)s is still in progress at operation %(op)s; '
                'finish the pass there (OK/NG/scrap) before starting '
                'rework.', sn=serial_identity.name,
                op=wip.route_operation_id.display_label))
        if self._oqc_serial_already_received(serial_identity):
            raise ValidationError(_(
                'SN %(sn)s has already been received into stock; use the '
                'stock correction process instead of rework.',
                sn=serial_identity.name))
        serial_identity.x_rework_count += 1
        serial_identity.x_rework_inspection_id = self.id
        serial_identity.x_rework_order_id = order.id
        serial_identity.x_rework_operation_id = route_operation.id
        serial_identity.x_rework_started_at = fields.Datetime.now()
        # 截断水位：发起时刻该 SN 已有的最大历史行 id——之后的重走
        # 只认 id 更大的行（任务 5.3，秒级时间戳在同秒内分不开新旧）
        watermark = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', serial_identity.id)],
            order='id desc', limit=1).id or 0
        serial_identity.x_rework_history_watermark = watermark
        # 处置审计（oqc-disposition-closure 决策 2，任务 2.2）：返工授权落
        # rework_start 事件（state_after=reworking），完成闸门与释放条件按
        # 处置状态口径消费；回流到站/复测确认事件由批次 3 在此基础上接线
        info = self._oqc_current_dispositions(
            serial_identity).get(serial_identity.id) or {}
        chain_defect = self.env['sn.wsd.quality.oqc.disposition.event'].search([
            ('inspection_id', '=', self.id),
            ('serial_identity_id', '=', serial_identity.id),
            ('defect_code_id', '!=', False),
        ], order='id desc', limit=1)
        self._oqc_append_events([{
            'serial_identity_id': serial_identity.id,
            'action': 'rework_start',
            'state_before': info['state'] if info.get('event_id') else False,
            'state_after': 'reworking',
            'attempt_no': serial_identity.x_rework_count,
            'reason': (reason or '').strip(),
            'defect_code_id': chain_defect.defect_code_id.id,
            'before_snapshot': dict(self._oqc_batch_snapshot(),
                                    **self._oqc_cell_snapshot(serial_identity)),
            'after_snapshot': dict(
                self._oqc_batch_snapshot(),
                target_operation=route_operation.display_label),
            'route_operation_id': route_operation.id,
            'source_key': 'oqc-rework-start-%s-%s-%s' % (
                self.id, serial_identity.id, serial_identity.x_rework_count),
        }])
        serial_identity.x_rework_event_id_value = self.env[
            'sn.wsd.quality.oqc.disposition.event'].search([
                ('inspection_id', '=', self.id),
                ('serial_identity_id', '=', serial_identity.id)],
                order='id desc', limit=1).id
        self.message_post(body=_(
            'Rework: SN %(sn)s pulled back to operation %(op)s '
            '(attempt %(attempt)s). Reason: %(reason)s',
            sn=serial_identity.name, op=route_operation.display_label,
            attempt=serial_identity.x_rework_count,
            reason=(reason or '').strip()))
        return True

    def _oqc_rework_pending_count(self):
        self.ensure_one()
        return self.env['sn.wsd.serial.identity'].search_count([
            ('x_rework_inspection_id', '=', self.id)])

    def action_reset_open(self):
        # OQC 过站矩阵单的重开走处置服务（任务 2.2）：多记一条 reopen 事件
        # （旧批次结论入快照，历史不覆盖）；state/finish_time 写法与原方法
        # 一致，AQL 快照不动。其他类型单据保持原语义。
        station_oqc = self.filtered(lambda i: i._oqc_station_mode())
        for inspection in station_oqc:
            inspection._oqc_reopen_for_disposition()
        others = self - station_oqc
        if others:
            super(QualityInspectionDisposition,
                  others).action_reset_open()
        return True

    # ------------------------------------------------------------------
    # Rejected-lot switch: reopen and let every board through the gate
    # ------------------------------------------------------------------
    def action_open_full_close_wizard(self):
        """数量差异收口入口（任务 3.3）：全检单已检 < 批量时的确认
        弹窗；确认与理由由向导采集，收口检查仍在 action_done 内。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Close Full-Lot Inspection with Quantity Gap'),
            'res_model': 'sn.wsd.quality.oqc.full.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_inspection_id': self.id},
        }

    def action_start_full_inspection(self):
        self.ensure_one()
        if self.inspection_type != 'oqc' or self.state != 'done' \
                or self.result in ('pass', 'concession'):
            raise UserError(_(
                'Full-lot inspection starts from a rejected outgoing '
                'inspection.'))
        self.x_full_inspection = True
        return self.action_reset_open()


class MesOrderReworkMark(models.Model):
    """Rework boards leave a mark on their re-walked pass rows so the
    ledger and reports can tell them from first-pass production."""

    _inherit = 'sn.wsd.mes.order'

    def _prepare_leave_history_vals(self, serial_identity, route_operation,
                                    wip, result, scrap_reason=False,
                                    ng_defect=False, operator_code=False,
                                    workcenter=False):
        vals = super()._prepare_leave_history_vals(
            serial_identity, route_operation, wip, result,
            scrap_reason=scrap_reason, ng_defect=ng_defect,
            operator_code=operator_code, workcenter=workcenter)
        if serial_identity.x_rework_inspection_id:
            vals['x_is_rework'] = True
        return vals


class QualityInspectionCellDispositionEvent(models.Model):
    """人工格提交差异接线（oqc-disposition-closure 任务 1.5）：OQC 过站
    矩阵的结果格被实际改值时落审计事件。程序化铺格（_oqc_on_leave /
    _oqc_ensure_cells / _fai_expand_result_cells）携带静音标志走自己
    的记账路径，避免双事件。"""

    _inherit = 'sn.wsd.quality.inspection.cell'

    def write(self, vals):
        watched = self.env['sn.wsd.quality.inspection.cell']
        if not self.env.context.get('sn_wsd_oqc_cell_silent') \
                and {'measured_value', 'text_value', 'manual_result',
                     'defect_code_id'}.intersection(vals):
            watched = self.filtered(
                lambda c: c.inspection_id._oqc_station_mode())
        before = {
            cell.id: cell._oqc_event_cell_snapshot() for cell in watched}
        res = super().write(vals)
        if watched:
            watched.mapped('inspection_id')._oqc_log_cell_edit_events(
                watched, before)
        return res

    def _oqc_event_cell_snapshot(self):
        """值快照（决策 1）：项目编码/名称/标准/上下限、值、判定、缺陷
        与备注的纯值，用于事件 before/after 与同值保存判重。"""
        self.ensure_one()
        return {
            'item_code': self.line_id.item_code,
            'item_name': self.line_id.name,
            'item_type': self.line_id.item_type,
            'lower_limit': self.line_id.lower_limit,
            'upper_limit': self.line_id.upper_limit,
            'expected_value': self.line_id.expected_value,
            'measured_value': self.measured_value,
            'text_value': self.text_value,
            'manual_result': self.manual_result,
            'result': self.result,
            'defect_code': (self.defect_code_id.code
                            or self.defect_code_id.name or False)
            if self.defect_code_id else False,
            'note': self.note,
        }
