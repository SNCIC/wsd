from odoo import _, api, fields, models
from odoo.exceptions import AccessError

# 单板处置进度（oqc-disposition-closure 决策 2 的状态迁移全集）：
# 派生口径 = (inspection, serial) 最新事件的 state_after，绝不回填到板上
OQC_DISPOSITION_STATE_SELECTION = [
    ('pending', 'Awaiting Disposition'),
    ('reworking', 'Reworking'),
    ('awaiting_reinspection', 'Awaiting Re-inspection'),
    ('retest_passed', 'Retest Passed'),
    ('scrapped', 'Scrapped'),
    ('concession', 'Concession Accepted'),
]

# 已结案状态：新 NG 事实到来时重新进入 pending（追加新事件，不覆盖）
OQC_DISPOSITION_CLOSED_STATES = ('retest_passed', 'scrapped', 'concession')


class OqcDispositionEvent(models.Model):
    """OQC 处置只追加审计事件（oqc-disposition-closure 决策 1/6）。

    一行记录一个不可覆盖的事实：NG 发现、人工格编辑、复测、返工段、
    报废、让步、重开或升级基线。单板当前处置状态由 (检验单, SN) 的
    最新事件 state_after 派生，不在板上存第二份。

    模型对通用 RPC 封闭：create 仅在超级用户 + 私有服务上下文标志
    （见检验单的 _oqc_append_events）下放行——可伪造的 context 标志
    本身不是保护，真正的门是 self.env.su，普通 RPC 调用（含 admin）
    恒为非 su；write/unlink 一律拒绝（历史不可改、不可删），restrict
    外键防止删主单级联抹掉审计。读权限跟随多公司 ir.rule，业务用户
    只读。"""

    _name = 'sn.wsd.quality.oqc.disposition.event'
    _description = 'WSD OQC Disposition Event'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection', string='Inspection', required=True,
        index=True, ondelete='restrict', check_company=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True, index=True,
        ondelete='restrict', check_company=True,
    )
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN', index=True,
        ondelete='restrict', check_company=True,
        help='Board this event is about. Batch-level events (reopen, '
             'full-lot closure, concession scope) leave it empty.',
    )
    action = fields.Selection(
        [
            ('baseline', 'Upgrade Baseline'),
            ('detected', 'NG Detected'),
            ('result_edit', 'Result Edit'),
            ('retest', 'Retest Confirmed'),
            ('rework_start', 'Rework Started'),
            ('rework_arrive', 'Rework Back at OQC'),
            ('rework_ng', 'Rework Failed Again'),
            ('scrap', 'Scrapped'),
            ('scrap_restore', 'Scrap Restored'),
            ('concession', 'Concession Accepted'),
            ('reopen', 'Inspection Reopened'),
            ('full_close', 'Full Inspection Closed'),
        ],
        string='Action', required=True, index=True,
    )
    state_before = fields.Selection(
        OQC_DISPOSITION_STATE_SELECTION, string='State Before',
    )
    state_after = fields.Selection(
        OQC_DISPOSITION_STATE_SELECTION, string='State After', index=True,
    )
    attempt_no = fields.Integer(
        string='Rework Attempt',
        help='Rework attempt counter of the board at event time. '
             'Informational only, no business ceiling.',
    )
    reason = fields.Text(
        string='Reason',
        help='Mandatory on manual disposition actions; automatic events '
             'carry an explicit source description.',
    )
    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code', string='Defect Code',
        check_company=True, index=True,
        help='Defect identity established for the board. Closure actions '
             'require one; raw device text alone never closes a board.',
    )
    defect_code_raw = fields.Text(
        string='Raw Defect Code',
        help='Device-side defect text as uploaded, kept verbatim when the '
             'dictionary has no match. Never overwrites defect_code_id.',
    )
    before_snapshot = fields.Json(
        string='Before Snapshot',
        help='Value snapshot (item codes/names/limits, values, verdicts, '
             'defects, scope, batch conclusion) before the event.',
    )
    after_snapshot = fields.Json(
        string='After Snapshot',
        help='Value snapshot after the event. Values and related ids '
             'only, never recordsets.',
    )
    operator_id = fields.Many2one(
        'res.users', string='Operator', required=True, index=True,
        default=lambda self: self.env.user,
    )
    event_time = fields.Datetime(
        string='Event Time', required=True, index=True,
        default=fields.Datetime.now,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Route Operation',
        check_company=True, index=True, ondelete='restrict',
    )
    history_id = fields.Many2one(
        'sn.wsd.serial.operation.history', string='Station History',
        check_company=True, index=True, ondelete='restrict',
        help='Station pass row that carried the NG fact, when the event '
             'was detected by a station leave.',
    )
    source_key = fields.Char(
        string='Source Key', required=True, copy=False,
        help='Idempotency token: devices reuse the station history '
             'identity, manual actions use action + inspection + SN + '
             'latest event version.',
    )

    _source_key_company_uniq = models.Constraint(
        'unique(company_id, source_key)',
        'The OQC disposition event source key must be unique per company.',
    )

    def action_open_station_history(self):
        """原始过站记录入口（任务 7.3）：跳过站历史列表，按本事件板 +
        制令单过滤——历次 NG/OK/报废过站逐行可见，与事件快照互证。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SN Operation History'),
            'res_model': 'sn.wsd.serial.operation.history',
            'view_mode': 'list',
            'domain': [
                ('serial_identity_id', '=', self.serial_identity_id.id),
                ('mes_order_id', '=', self.mes_order_id.id),
            ],
        }

    # ------------------------------------------------------------------
    # 只追加保护（决策 6）：私有服务在 sudo + 内部标志下创建；写/删拒绝
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su
                and self.env.context.get('sn_wsd_oqc_event_internal')):
            raise AccessError(_(
                'OQC disposition events can only be created by the '
                'quality inspection services.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_(
            'OQC disposition events are append-only: existing events '
            'cannot be modified.'))

    def unlink(self):
        raise AccessError(_(
            'OQC disposition events are append-only: existing events '
            'cannot be deleted.'))

    def _auto_init(self):
        """Composite indexes for the latest-event projections (decision 1):
        per (company, inspection, serial) and per (company, order), both
        descending by id so the newest event of a board reads from the
        index head. Created on install and on every upgrade."""
        res = super()._auto_init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sn_wsd_quality_oqc_event_insp_serial_idx
            ON sn_wsd_quality_oqc_disposition_event
               (company_id, inspection_id, serial_identity_id, id DESC)
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sn_wsd_quality_oqc_event_order_idx
            ON sn_wsd_quality_oqc_disposition_event
               (company_id, mes_order_id, id DESC)
        """)
        return res
