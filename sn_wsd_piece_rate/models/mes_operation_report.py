from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MesOperationReport(models.Model):
    """piece-rate 扩展：报工行的计件占用状态 + 人员分配（唯一事实）。

    一笔报工行最多存在一张未作废的计件单（草稿即占用，作废释放）——
    x_piece_settled 即该口径的只读判定，供向导/开单 domain 过滤；
    x_piece_settled_label 是它的人读版本，列表里以文本徽章展示。

    report-daily-workbench：报工行携带人员分配（参与人 + 绩效比）与
    班组底稿。计件草稿的参与人由这里原样复制，结算侧只读；修改窗口 =
    对应计件草稿未确认前（确认后冻结，纠错只能作废重走）。
    """
    _inherit = 'sn.wsd.mes.operation.report'

    piece_settlement_ids = fields.One2many(
        'sn.wsd.piece.settlement', 'operation_report_id',
        string='Piece Settlements')
    x_piece_settled = fields.Boolean(
        string='Piece Settled (Flag)',
        compute='_compute_piece_settled',
        search='_search_piece_settled',
        help='True when a non-void piece settlement references this report.')
    x_piece_settled_label = fields.Char(
        string='Piece Settled',
        compute='_compute_piece_settled_label',
        help='Human-readable badge for the piece-settled column.')
    team_id = fields.Many2one(
        'sn.mrp.team', string='Team',
        check_company=True,
        domain="[('production_line_id', '=', production_line_id)]",
        help='Team used to pre-fill participants and their performance '
             'ratios (normalized over the participating subset). Drafting '
             'base only: the allocation truth is the participant rows.')
    production_line_id = fields.Many2one(
        'sn.mrp.production.line', string='Production Line',
        related='mes_order_id.production_line_id', store=True, index=True)
    participant_ids = fields.One2many(
        'sn.wsd.mes.operation.report.participant', 'report_id',
        string='Participants',
        help='People who produced this batch, with their performance '
             'ratios. Copied as-is into the piece settlement draft.')
    participant_count = fields.Integer(compute='_compute_participant_count')
    participant_summary = fields.Char(
        string='Allocation', compute='_compute_participant_summary',
        help='Compact view of the participants and their ratios.')

    @api.depends('piece_settlement_ids.state')
    def _compute_piece_settled(self):
        for report in self:
            report.x_piece_settled = bool(
                report.piece_settlement_ids.filtered(lambda s: s.state != 'void'))

    @api.depends('x_piece_settled')
    def _compute_piece_settled_label(self):
        for report in self:
            report.x_piece_settled_label = (
                _('Settled') if report.x_piece_settled else _('Unsettled'))

    @api.depends('participant_ids')
    def _compute_participant_count(self):
        for report in self:
            report.participant_count = len(report.participant_ids)

    @api.depends('participant_ids.employee_id', 'participant_ids.performance_ratio')
    def _compute_participant_summary(self):
        for report in self:
            report.participant_summary = ' / '.join(
                f'{p.employee_id.name} {p.performance_ratio:g}%'
                for p in report.participant_ids.sorted('sequence'))

    def _search_piece_settled(self, operator, value):
        # Odoo 19 会把 '= True' 规范成 ('in', [True]) 传入，value 可能是集合
        values = value if isinstance(value, (list, tuple, set)) else [value]
        truthy = any(bool(v) for v in values)
        want_settled = truthy if operator in ('=', 'in') else not truthy
        settlements = self.env['sn.wsd.piece.settlement'].search([
            ('state', '!=', 'void'),
            ('operation_report_id', '!=', False),
        ])
        settled_ids = settlements.mapped('operation_report_id').ids
        return [('id', 'in' if want_settled else 'not in', settled_ids)]

    # ------------------------------------------------------------------
    # allocation landing (hook called by report_operation_qty)
    # ------------------------------------------------------------------

    def _apply_report_allocation(self, participant_vals, team_id):
        """Persist the optional allocation arguments of
        report_operation_qty: team + participant rows. Called on the newly
        created report row right after its creation."""
        self.ensure_one()
        vals = {}
        if team_id:
            vals['team_id'] = (
                team_id.id if not isinstance(team_id, int) else team_id)
        if participant_vals:
            vals['participant_ids'] = [
                (0, 0, {
                    'employee_id': line['employee_id'],
                    'performance_ratio': line.get('performance_ratio', 0.0),
                    'sequence': line.get(
                        'sequence', 10 * (index + 1)),
                }) for index, line in enumerate(participant_vals)]
        if vals:
            self.write(vals)
        return self

    # ------------------------------------------------------------------
    # submit-entry guard: allocation mandatory when a rate is configured
    # ------------------------------------------------------------------

    @api.model
    def _check_allocation_required(self, company, product, operation,
                                   qty_ok, participants):
        """Daily-reporting submit guard: when a piece rate is configured
        for (company, product, operation) and qty_ok > 0, the line must
        carry at least one participant and the ratios must total 100%
        (+/- 0.01). No rate configured (or a pure NG/scrap line) → not
        enforced. participants is an iterable of (employee, ratio)."""
        if not company or not product or not operation or qty_ok <= 0:
            return
        rate = self.env['sn.wsd.piece.rate'].sudo().search([
            ('company_id', '=', company.id),
            ('product_id', '=', product.id),
            ('operation_id', '=', operation.id),
        ], limit=1)
        if not rate:
            return
        participants = list(participants)
        if not participants:
            raise ValidationError(_(
                'A piece rate is configured for product %(product)s on '
                'operation %(operation)s: select the participants who '
                'produced this batch.', product=product.display_name,
                operation=operation.display_name))
        seen = set()
        total = 0.0
        for employee, ratio in participants:
            if employee.id in seen:
                raise ValidationError(_(
                    'Employee %(employee)s appears twice in the '
                    'allocation of product %(product)s on operation '
                    '%(operation)s.', employee=employee.display_name,
                    product=product.display_name,
                    operation=operation.display_name))
            seen.add(employee.id)
            if ratio < 0 or ratio > 100:
                raise ValidationError(_(
                    'The performance ratio of %(employee)s must be between '
                    '0 and 100.', employee=employee.display_name))
            total += ratio
        if abs(total - 100.0) > 0.01:
            raise ValidationError(_(
                'The participant ratio total of product %(product)s on '
                'operation %(operation)s must be 100%% (currently '
                '%(total)s%%).', product=product.display_name,
                operation=operation.display_name, total=round(total, 4)))

    # ------------------------------------------------------------------
    # allocation edit window: frozen after confirm, synced while draft
    # ------------------------------------------------------------------

    def _check_allocation_editable(self):
        """Raise when any referencing settlement is confirmed: the
        allocation of the report row is then frozen and the fix path is
        void the settlement, edit the allocation, generate again."""
        Settlement = self.env['sn.wsd.piece.settlement'].sudo()
        for report in self:
            frozen = Settlement.search([
                ('operation_report_id', '=', report.id),
                ('state', '=', 'confirmed'),
            ], limit=1)
            if frozen:
                raise UserError(_(
                    'The allocation of the report on order %(order)s / '
                    'operation %(operation)s is frozen: settlement '
                    '%(settlement)s is confirmed. Void the settlement, '
                    'edit the allocation and generate it again.',
                    order=report.mes_order_id.name,
                    operation=report.route_operation_id.display_label,
                    settlement=frozen.name))

    def _sync_draft_settlement_participants(self):
        """Mirror the report allocation onto every referencing DRAFT
        settlement (participants copied as-is; amounts recompute). Called
        by the participant guard after any create/write/unlink."""
        Settlement = self.env['sn.wsd.piece.settlement'].sudo()
        for report in self:
            drafts = Settlement.search([
                ('operation_report_id', '=', report.id),
                ('state', '=', 'draft'),
            ])
            if not drafts:
                continue
            commands = [fields.Command.clear()] + [
                fields.Command.create({
                    'employee_id': p.employee_id.id,
                    'performance_ratio': p.performance_ratio,
                    'x_ratio_baseline': p.performance_ratio,
                    'sequence': p.sequence,
                }) for p in report.participant_ids.sorted('sequence')]
            drafts.write({
                'participant_ids': commands,
                'team_id': report.team_id.id,
            })

    # ------------------------------------------------------------------
    # best-effort auto draft (called by the sn_wsd_piece_rate override of
    # report_operation_qty after the report row landed)
    # ------------------------------------------------------------------

    def _piece_maybe_auto_settlement(self):
        """Create the piece settlement draft for this report row when
        every condition holds: qty_ok > 0, participants present, a rate
        configured for (company, product, operation) and the business
        month (report date) open. Any miss → silent skip: the row simply
        stays 'to allocate'. Exceptions are caught by the caller and never
        block the reporting itself."""
        Settlement = self.env['sn.wsd.piece.settlement'].sudo()
        CloseLog = self.env['sn.wsd.piece.close.log']
        Rate = self.env['sn.wsd.piece.rate'].sudo()
        for report in self:
            if report.qty_ok <= 0 or not report.participant_ids:
                continue
            if report.x_piece_settled:
                continue
            date = (report.reported_at.date() if report.reported_at
                    else fields.Date.context_today(report))
            if CloseLog._month_closed(report.company_id, date):
                continue
            rate = Rate.search([
                ('company_id', '=', report.company_id.id),
                ('product_id', '=', report.mes_order_id.product_id.id),
                ('operation_id', '=',
                 report.route_operation_id.operation_id.id),
            ], limit=1)
            if not rate:
                continue
            settlement = Settlement.create({
                'mes_order_id': report.mes_order_id.id,
                'route_operation_id': report.route_operation_id.id,
                'operation_report_id': report.id,
                'qty_ok': report.qty_ok,
                'date': date,
                'team_id': report.team_id.id,
                'participant_ids': [
                    (0, 0, {
                        'employee_id': p.employee_id.id,
                        'performance_ratio': p.performance_ratio,
                        'x_ratio_baseline': p.performance_ratio,
                        'sequence': p.sequence,
                    }) for p in report.participant_ids.sorted('sequence')],
            })
            settlement._resolve_rate_price()

    # ------------------------------------------------------------------
    # allocation quick-fill (to-allocate tab / report ledger form)
    # ------------------------------------------------------------------

    def action_fill_from_team(self):
        """Replace the participants with the team members, ratios
        normalized to 100% (same caliber as the settlement fill)."""
        Settlement = self.env['sn.wsd.piece.settlement']
        for report in self:
            if not report.team_id:
                raise UserError(_('Select a team first.'))
            members = report.team_id.member_ids
            if not members:
                raise UserError(_('The team has no members.'))
            ratios = Settlement._distribute_ratios(
                members.mapped('performance_ratio'))
            report.participant_ids = [fields.Command.clear()] + [
                fields.Command.create({
                    'employee_id': member.employee_id.id,
                    'performance_ratio': ratio,
                    'sequence': 10 * (index + 1),
                }) for index, (member, ratio) in enumerate(
                    zip(members, ratios))]

    def action_equal_split(self):
        Settlement = self.env['sn.wsd.piece.settlement']
        for report in self:
            participants = report.participant_ids.sorted('sequence')
            if not participants:
                raise UserError(_('Add participants first.'))
            ratios = Settlement._distribute_ratios(
                [1.0] * len(participants))
            for participant, ratio in zip(participants, ratios):
                participant.performance_ratio = ratio

    def action_open_allocation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Operation Report'),
            'res_model': 'sn.wsd.mes.operation.report',
            'res_id': self.id,
            'view_mode': 'form',
        }


class MesOperationReportParticipant(models.Model):
    """报工行参与人（report-daily-workbench）：员工 + 绩效比。

    报工行是人员分配的唯一事实；计件草稿按 (员工, 比例) 原样复制。
    修改守卫：报工行存在已确认（非 void）结算 → 拒绝（指引作废重走）；
    存在草稿 → 写后同步草稿参与人并重算金额。
    """
    _name = 'sn.wsd.mes.operation.report.participant'
    _description = 'MES Operation Report Participant'
    _order = 'report_id, sequence, id'
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    report_id = fields.Many2one(
        'sn.wsd.mes.operation.report', required=True, ondelete='cascade',
        index=True)
    company_id = fields.Many2one(
        'res.company', related='report_id.company_id', store=True, index=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        check_company=True, ondelete='restrict')
    employee_code = fields.Char(
        related='employee_id.barcode', string='Employee Code', store=True)
    performance_ratio = fields.Float(
        string='Performance Ratio', digits=(12, 4), required=True,
        default=0.0)

    _report_participant_unique = models.Constraint(
        'unique(report_id, employee_id)',
        'The employee is already a participant of this report.',
    )
    _report_participant_ratio_range = models.Constraint(
        'CHECK(performance_ratio >= 0 AND performance_ratio <= 100)',
        'The performance ratio must be between 0 and 100.',
    )

    def _guarded_reports(self, vals=False):
        reports = self.mapped('report_id')
        if vals and vals.get('report_id'):
            reports |= self.env['sn.wsd.mes.operation.report'].browse(
                [vals['report_id']])
        return reports

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._guarded_reports(vals)._check_allocation_editable()
        participants = super().create(vals_list)
        participants.mapped('report_id')._sync_draft_settlement_participants()
        return participants

    def write(self, vals):
        self._guarded_reports(vals)._check_allocation_editable()
        result = super().write(vals)
        self.mapped('report_id')._sync_draft_settlement_participants()
        return result

    def unlink(self):
        reports = self.mapped('report_id')
        reports._check_allocation_editable()
        result = super().unlink()
        reports._sync_draft_settlement_participants()
        return result
