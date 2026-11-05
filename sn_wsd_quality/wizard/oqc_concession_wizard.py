from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OqcConcessionWizard(models.TransientModel):
    """整批让步（oqc-disposition-closure 决策 2/5，任务 2.3）：必填理由
    + 范围确认。打开时展示待让步 SN 范围与硬拦原因并快照各 SN 的最新
    事件版本；提交在共享锁序列（检验单 → SN id 升序）内复核版本与硬拦，
    通过后逐板落 concession 事件 + 一条批次级范围事件，再置 done/
    concession。不伪造测试 OK：不改格、不写过站。"""

    _name = 'sn.wsd.quality.oqc.concession.wizard'
    _description = 'OQC Batch Concession'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
    )
    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection', string='Inspection', required=True,
        ondelete='cascade', check_company=True)
    reason = fields.Text(
        string='Concession Reason', required=True,
        help='Mandatory: why the batch is accepted with the known defects.')
    scope_serial_ids = fields.Many2many(
        'sn.wsd.serial.identity',
        'sn_wsd_quality_oqc_concession_wizard_serial_rel',
        'wizard_id', 'serial_id', string='Concession Scope', readonly=True,
        help='Boards awaiting disposition that this concession accepts. '
             'Confirmed as-is on submit; a concurrent change refuses the '
             'apply until the scope is refreshed.')
    hard_block_reasons = fields.Text(
        string='Blocking Conditions', readonly=True,
        help='Why the concession cannot close the batch yet (incomplete '
             'sample set, pending required items, rework in progress...).')
    expected_versions = fields.Json(
        string='Expected Versions',
        help='Latest disposition event id per scope SN when the wizard was '
             'opened; a mismatch on submit means the scope changed.')

    # ------------------------------------------------------------------
    # 预填（展示用；资格由提交侧在锁内重算校验——决策 5）
    # ------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        inspection = self.env['sn.wsd.quality.inspection'].browse(
            defaults.get('inspection_id')
            or self.env.context.get('default_inspection_id'))
        if not inspection.exists() or not inspection._oqc_station_mode():
            return defaults
        dispositions = inspection._oqc_current_dispositions()
        scope = sorted(sid for sid, info in dispositions.items()
                       if info.get('state') == 'pending')
        defaults['company_id'] = inspection.company_id.id
        defaults['scope_serial_ids'] = [(6, 0, scope)]
        defaults['expected_versions'] = {
            sid: (dispositions[sid].get('event_id') or False)
            for sid in scope}
        defaults['hard_block_reasons'] = '\n'.join(
            '- %s' % reason
            for reason in self._concession_hard_blocks(inspection)) or False
        return defaults

    # ------------------------------------------------------------------
    # 硬拦条件（打开与提交共用；提交侧在锁内重算）
    # ------------------------------------------------------------------
    def _concession_hard_blocks(self, inspection):
        inspection.ensure_one()
        reasons = []
        if not inspection.x_full_inspection:
            arrived = len(inspection.x_fai_arrived_serial_ids
                          | inspection.x_oqc_ng_serial_ids)
            if arrived < inspection.sample_size:
                reasons.append(_(
                    'The sample set is incomplete: only %s of %s expected '
                    'samples reached the outgoing operation.',
                    arrived, inspection.sample_size))
        missing = inspection.line_ids.filtered(
            lambda line: line.required and line.result == 'pending')
        if missing:
            reasons.append(_(
                'Required inspection items are still pending: %s.',
                ', '.join(sorted(set(missing.mapped('name'))))))
        # 未确认的报废草稿也是未结处置（任务 6.2）：让步前必须先确认
        # 或取消——软引用 sn_wsd_scrap（未安装时无此模型，跳过）
        Scrap = self.env.get('sn.wsd.scrap.record')
        if Scrap is not None:  # env.get returns an empty (falsy) recordset
            drafts = Scrap.search([
                ('mes_order_id', '=', inspection.mes_order_id.id),
                ('state', '=', 'draft'),
            ])
            if drafts:
                reasons.append(_(
                    'Unconfirmed scrap drafts: %s. Confirm or cancel them '
                    'before a concession.',
                    ', '.join(drafts.mapped('name'))))
        labels = {'reworking': 'in rework',
                  'awaiting_reinspection': 'awaiting re-inspection'}
        groups = inspection._oqc_open_disposition_serials(
            ('reworking', 'awaiting_reinspection'))
        for state in ('reworking', 'awaiting_reinspection'):
            serials = groups.get(state)
            if serials:
                reasons.append(_(
                    '%s board(s) still %s: %s.', len(serials), labels[state],
                    ', '.join(sorted(serials.mapped('name')))))
        # TODO(oqc-disposition-closure batch 6): refuse the concession while
        # scrap drafts (sn.wsd.scrap.record in state 'draft') exist for boards
        # of this inspection. quality must not depend on sn_wsd_scrap, so the
        # check is wired by the scrap-side extension together with scrap
        # events; until then only defect codes and disposition states are
        # verified here.
        return reasons

    def _normalized_expected_versions(self):
        """Json 键经序列化变字符串：统一回 int SN id 再比对。"""
        return {int(sid): (event_id or False)
                for sid, event_id in (self.expected_versions or {}).items()}

    def _latest_chain_defect(self, inspection, serial):
        return self.env['sn.wsd.quality.oqc.disposition.event'].search([
            ('inspection_id', '=', inspection.id),
            ('serial_identity_id', '=', serial.id),
            ('defect_code_id', '!=', False),
        ], order='id desc', limit=1).defect_code_id

    # ------------------------------------------------------------------
    # 提交：锁内复核 → 事件 → done/concession
    # ------------------------------------------------------------------
    def action_apply(self):
        self.ensure_one()
        inspection = self.inspection_id
        if not inspection._oqc_station_mode():
            raise UserError(_(
                'Batch concessions apply to outgoing inspections of '
                'station-mode MES orders only.'))
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_('Describe the concession reason.'))
        expected = self._normalized_expected_versions()
        dispositions = inspection._oqc_current_dispositions()
        pending = {sid for sid, info in dispositions.items()
                   if info.get('state') == 'pending'}
        if not pending:
            # 让步不代替尚未发生的检验（spec「让步不代替尚未发生的检
            # 验」）：返工中/待复检任务先行拒绝，再谈"无可让步范围"
            busy = [info.get('state') for info in dispositions.values()
                    if info.get('state') in ('reworking',
                                             'awaiting_reinspection')]
            if busy:
                raise UserError(_(
                    'Inspection %s still has boards in rework or awaiting '
                    're-inspection: finish them before a concession.',
                    inspection.name))
            raise UserError(_(
                'No board is awaiting disposition on inspection %s: there '
                'is nothing to accept by concession.', inspection.name))
        if set(expected) != pending:
            raise UserError(_(
                'The disposition scope changed since the confirmation was '
                'loaded; refresh the concession and confirm the new scope.'))
        serials = self.env['sn.wsd.serial.identity'].browse(sorted(pending))
        # 共享锁序列（决策 6）：锁内复读最新事件与范围，并发新增 NG /
        # 结案一律拒绝为"范围已变化，请刷新"
        inspection._oqc_lock(serials)
        pending_locked = {
            sid for sid, info
            in inspection._oqc_current_dispositions().items()
            if info.get('state') == 'pending'}
        scope_locked = inspection._oqc_current_dispositions(serials)
        if pending_locked != pending or any(
                info.get('state') != 'pending'
                for info in scope_locked.values()):
            raise UserError(_(
                'The disposition scope changed since the confirmation was '
                'loaded; refresh the concession and confirm the new scope.'))
        # 统一资格校验（版本/状态/缺陷码/冻结/报废）+ 硬拦（锁内重算）
        inspection._oqc_check_action(
            'concession', serials, expected_versions=expected)
        reasons = self._concession_hard_blocks(inspection)
        if reasons:
            raise UserError(_(
                'The concession cannot accept this batch yet:\n%s',
                '\n'.join('- %s' % item for item in reasons)))
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        token = Event.search([
            ('inspection_id', '=', inspection.id)],
            order='id desc', limit=1).id or 0
        # done 单开始处置 = 先重开记旧结论（任务 2.2）
        if inspection.state == 'done':
            inspection._oqc_reopen_for_disposition()
        ordered = serials.sorted(key=lambda s: s.id)
        events = [{
            'serial_identity_id': serial.id,
            'action': 'concession',
            'state_before': 'pending',
            'state_after': 'concession',
            'attempt_no': serial.x_rework_count or 0,
            'reason': reason,
            'defect_code_id': self._latest_chain_defect(
                inspection, serial).id,
            'before_snapshot': dict(inspection._oqc_batch_snapshot(),
                                    source='batch_concession'),
            'after_snapshot': dict(inspection._oqc_batch_snapshot(),
                                   **inspection._oqc_cell_snapshot(serial)),
            'route_operation_id': inspection.route_operation_id.id,
            'source_key': 'oqc-concession-%s-%s-%s' % (
                inspection.id, serial.id, token),
        } for serial in ordered]
        # 批次级范围事件（serial 空，决策 1：范围与理由入快照）
        events.append({
            'action': 'concession',
            'reason': reason,
            'before_snapshot': inspection._oqc_batch_snapshot(),
            'after_snapshot': dict(
                inspection._oqc_batch_snapshot(),
                scope=[{'id': serial.id, 'name': serial.name}
                       for serial in ordered],
                reason=reason),
            'source_key': 'oqc-concession-%s-%s' % (inspection.id, token),
        })
        inspection._oqc_append_events(events)
        # 不伪造测试 OK（决策 3）：不改格、不写过站，仅批次结论让步
        inspection.write({
            'result': 'concession',
            'state': 'done',
            'finish_time': fields.Datetime.now(),
        })
        return {'type': 'ir.actions.act_window_close'}
