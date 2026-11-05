from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

ACTIVE_REPORT_STATES = ('released', 'picked', 'in_progress')


class PieceReportWizardLine(models.TransientModel):
    """日报工的行（report-daily-workbench；report-daily-price-inline 单页签）。

    一行 = 一个活跃报工单（report 模式、released/picked/in_progress）
    私有路线上的一道工序：录 OK/NG/报废三数量、报废原因、班组与参与人，
    展示 计划量/已报/可报额度 与顺序锁状态。单价前置（report-daily-price-inline）：
    已配价只读展示（piece_price），未配价行上现填（x_new_price），提交时建入
    单价主数据。提交由向导的 action_submit_reports 在一个事务内逐行调
    report_operation_qty。
    """
    _name = 'sn.wsd.piece.report.wizard.line'
    _description = 'Daily Reporting Wizard Line'
    _order = 'wizard_id, sequence, id'

    wizard_id = fields.Many2one(
        'sn.wsd.piece.settlement.generate.wizard', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True,
        domain=[('x_manage_mode', '=', 'report'),
                ('state', 'in', ACTIVE_REPORT_STATES)],
        help='Active report-mode MES order (released / picked / in '
             'progress).')
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Operation', required=True,
        domain="[('mes_order_id', '=', mes_order_id)]",
        help='One operation of the private route of the selected order.')
    production_line_id = fields.Many2one(
        'sn.mrp.production.line', string='Production Line',
        related='mes_order_id.production_line_id')
    workshop_id = fields.Many2one(
        'sn.mrp.workshop', string='Workshop',
        related='production_line_id.workshop_id')
    qty_ok = fields.Float(string='OK Quantity')
    qty_ng = fields.Float(
        string='NG Quantity',
        help='Reworkable defects of this batch. Pure statistic: it does '
             'not consume the plan quota.')
    qty_scrap = fields.Float(
        string='Scrap Quantity',
        help='Unrecoverable loss of this batch. Consumes the plan quota.')
    scrap_reason_id = fields.Many2one(
        'sn.wsd.scrap.reason', string='Scrap Reason',
        domain="[('company_id', '=', company_id)]",
        help='Required whenever the scrap quantity is positive.')
    piece_price = fields.Float(
        string='Unit Price', digits=(12, 5), compute='_compute_piece_price',
        help='Price configured in the rate table for (company, product, '
             'operation). Zero means unconfigured: type the price on the '
             'line, it is created into the rate table at submit.')
    x_new_price = fields.Float(
        string='New Unit Price', digits=(12, 5),
        help='Price typed on the spot when no rate is configured yet: it is '
             'created into the rate table when the batch is submitted, so '
             'this batch and the next ones are priced. Ignored when a rate '
             'already exists (maintain changes in the configuration menu).')
    team_id = fields.Many2one(
        'sn.mrp.team', string='Team',
        check_company=True,
        domain="[('production_line_id', '=', production_line_id)]",
        help='Team used to pre-fill participants and their performance '
             'ratios (normalized over the participating subset).')
    participant_ids = fields.One2many(
        'sn.wsd.piece.report.wizard.participant', 'line_id',
        string='Participants')
    ratio_total = fields.Float(
        string='Ratio Total', compute='_compute_participants',
        help='Sum of the participant ratios; must reach 100% at submit.')
    participant_count = fields.Integer(compute='_compute_participants')
    participant_summary = fields.Char(
        string='Allocation', compute='_compute_participants')
    planned_qty = fields.Float(
        string='Planned Quantity', compute='_compute_progress',
        help='Planned quantity of the MES order.')
    reported_qty = fields.Float(
        string='Reported Quantity', compute='_compute_progress',
        help='Accumulated OK + scrap already reported at this operation.')
    remaining_qty = fields.Float(
        string='Plan Remainder', compute='_compute_progress',
        help='Planned minus accumulated OK + scrap: the room left for this '
             'batch (NG does not consume it).')
    sequence_locked = fields.Boolean(
        string='Sequence Locked', compute='_compute_progress',
        help='True when the predecessors have no more quantity to unlock '
             'this operation: an OK/scrap report would be rejected by the '
             'sequence lock.')
    company_id = fields.Many2one(
        'res.company', related='mes_order_id.company_id')

    @api.depends('company_id', 'mes_order_id.product_id',
                 'route_operation_id.operation_id')
    def _compute_piece_price(self):
        """Price of the rate master for (company, product, operation);
        0.0 = unconfigured (the rate constraint enforces price > 0)."""
        Rate = self.env['sn.wsd.piece.rate'].sudo()
        for line in self:
            price = 0.0
            if line.company_id and line.mes_order_id.product_id \
                    and line.route_operation_id.operation_id:
                rate = Rate.search([
                    ('company_id', '=', line.company_id.id),
                    ('product_id', '=', line.mes_order_id.product_id.id),
                    ('operation_id', '=',
                     line.route_operation_id.operation_id.id),
                ], limit=1)
                price = rate.price or 0.0
            line.piece_price = price

    @api.depends('participant_ids.employee_id',
                 'participant_ids.performance_ratio')
    def _compute_participants(self):
        for line in self:
            line.participant_count = len(line.participant_ids)
            line.ratio_total = sum(
                line.participant_ids.mapped('performance_ratio'))
            line.participant_summary = ' / '.join(
                f'{p.employee_id.name} {p.performance_ratio:g}%'
                for p in line.participant_ids.sorted('sequence'))

    @api.depends_context('lang')
    def _compute_display_name(self):
        """The detail panel header shows 'order / operation' instead of a
        raw 'model,id'."""
        for line in self:
            line.display_name = ' / '.join(filter(None, [
                line.mes_order_id.name,
                line.route_operation_id.display_label]))

    @api.depends('mes_order_id.planned_qty',
                 'route_operation_id.x_reported_ok_qty',
                 'route_operation_id.x_reported_scrap_qty',
                 'route_operation_id.blocked_by_ids.report_ids.qty_ok',
                 'route_operation_id.blocked_by_ids.report_ids.qty_scrap')
    def _compute_progress(self):
        Report = self.env['sn.wsd.mes.operation.report']
        for line in self:
            planned = line.mes_order_id.planned_qty
            reported = 0.0
            locked = False
            op = line.route_operation_id
            if op:
                # 口径与 report_operation_qty 的配额/顺序锁闸一致：
                # 累计 = OK + 报废（NG 纯统计不占额）。前置累计走 search
                # （sudo 建的报工行不进本环境 o2m 缓存，search 兜底防陈旧）
                reported = op.x_reported_ok_qty + op.x_reported_scrap_qty
                predecessors = op.blocked_by_ids
                if predecessors:
                    def _effective(pred):
                        reports = Report.search([
                            ('mes_order_id', '=', line.mes_order_id.id),
                            ('route_operation_id', '=', pred.id),
                        ])
                        return sum(reports.mapped(
                            lambda r: r.qty_ok + r.qty_scrap))
                    upstream_cap = max(
                        _effective(p) for p in predecessors)
                    locked = upstream_cap - reported <= 0.0001
            line.planned_qty = planned
            line.reported_qty = reported
            line.remaining_qty = planned - reported
            line.sequence_locked = locked

    # ------------------------------------------------------------------
    # prefill: last allocation of this operation, else team normalized
    # ------------------------------------------------------------------

    @api.model
    def _default_team_for(self, order):
        """Unique active team of the order's production line, else none."""
        if not order.production_line_id:
            return self.env['sn.mrp.team']
        teams = self.env['sn.mrp.team'].search([
            ('production_line_id', '=', order.production_line_id.id),
            ('active', '=', True),
        ])
        return teams if len(teams) == 1 else self.env['sn.mrp.team']

    @api.model
    def _participant_prefill(self, order, route_operation, team):
        """(team_id, participant commands) prefilled for a line:
        the last allocation reported on this operation, else the team
        members' ratios normalized to 100%."""
        Report = self.env['sn.wsd.mes.operation.report'].sudo()
        last = Report.search([
            ('mes_order_id', '=', order.id),
            ('route_operation_id', '=', route_operation.id),
            ('participant_ids', '!=', False),
        ], order='id desc', limit=1)
        if last:
            commands = [(0, 0, {
                'employee_id': p.employee_id.id,
                'performance_ratio': p.performance_ratio,
                'x_ratio_locked': False,
                'sequence': p.sequence,
            }) for p in last.participant_ids.sorted('sequence')]
            return (last.team_id.id or (team.id if team else False)), commands
        if team and team.member_ids:
            Settlement = self.env['sn.wsd.piece.settlement']
            ratios = Settlement._distribute_ratios(
                team.member_ids.mapped('performance_ratio'))
            commands = [(0, 0, {
                'employee_id': member.employee_id.id,
                'performance_ratio': ratio,
                'x_ratio_locked': False,
                'sequence': 10 * (index + 1),
            }) for index, (member, ratio) in enumerate(
                zip(team.member_ids, ratios))]
            return team.id, commands
        return False, []

    def _prefill_allocation(self):
        """Server-side prefill used both by the onchange and by the wizard
        load: keeps the team + participant rows in sync with the selected
        operation (last allocation first, team normalization as fallback)."""
        for line in self:
            if not line.mes_order_id or not line.route_operation_id:
                continue
            team = line.team_id or self._default_team_for(line.mes_order_id)
            team_id, commands = self._participant_prefill(
                line.mes_order_id, line.route_operation_id, team)
            line.team_id = team_id or (team.id if team else False)
            line.participant_ids = commands

    @api.onchange('mes_order_id')
    def _onchange_mes_order_id(self):
        if self.mes_order_id and self.route_operation_id \
                and self.route_operation_id.mes_order_id != self.mes_order_id:
            self.route_operation_id = False
            self.participant_ids = [(5, 0, 0)]

    @api.onchange('route_operation_id')
    def _onchange_route_operation_id_prefill(self):
        self._prefill_allocation()

    @api.onchange('team_id')
    def _onchange_team_id_fill_participants(self):
        """Picking or switching the team re-fills the participants from its
        members (normalized, locks cleared). Onchange on purpose: it must
        also work on the virtual rows of an unsaved wizard, where object
        buttons cannot run."""
        self._fill_from_team()

    def _fill_from_team(self):
        Settlement = self.env['sn.wsd.piece.settlement']
        for line in self:
            if not line.team_id or not line.team_id.member_ids:
                continue
            members = line.team_id.member_ids
            ratios = Settlement._distribute_ratios(
                members.mapped('performance_ratio'))
            line.participant_ids = [fields.Command.clear()] + [
                fields.Command.create({
                    'employee_id': member.employee_id.id,
                    'performance_ratio': ratio,
                    'x_ratio_locked': False,
                    'sequence': 10 * (index + 1),
                }) for index, (member, ratio) in enumerate(
                    zip(members, ratios))]

    def _rebalance_participants(self):
        """Explicit-lock rebalance (user decision 2026-11-01): locked rows
        keep their typed ratio; the remaining rows EQUALLY split the rest
        (the last one absorbs the rounding remainder). No automatic
        rebalance on typing or on row add/remove -- redistribution happens
        only on explicit actions: lock toggle, Equal Split, Fill From
        Team."""
        for line in self:
            rows = line.participant_ids
            if not rows:
                continue
            locked = rows.filtered('x_ratio_locked')
            auto = rows - locked
            if not auto:
                continue
            locked_total = sum(locked.mapped('performance_ratio'))
            remaining = 100.0 - locked_total
            if remaining < -0.01:
                continue  # locked rows already exceed 100%: leave as typed
            remaining = max(remaining, 0.0)
            auto_rows = list(auto)
            share = round(remaining / len(auto_rows), 4)
            # write through the skip flag: rows land one by one on their
            # way to a total that sums to (at most) 100
            for i, row in enumerate(auto_rows):
                row.with_context(sn_wsd_skip_ratio_check=True).write(
                    {'performance_ratio': share if i < len(auto_rows) - 1
                     else round(100.0 - locked_total
                                - share * (len(auto_rows) - 1), 4)})

    # ------------------------------------------------------------------
    # quick-fill buttons (same calibers as the settlement form)
    # ------------------------------------------------------------------

    def action_select_line(self):
        """Row button of the wizard list: mark this line as the one edited
        in the detail panel below."""
        for line in self:
            line.wizard_id.active_line_id = line

    def action_fill_from_team(self):
        for line in self:
            if not line.team_id:
                raise UserError(_('Select a team first.'))
            if not line.team_id.member_ids:
                raise UserError(_('The team has no members.'))
        self._fill_from_team()

    def action_equal_split(self):
        Settlement = self.env['sn.wsd.piece.settlement']
        for line in self:
            participants = line.participant_ids.sorted('sequence')
            if not participants:
                raise UserError(_('Add participants first.'))
            ratios = Settlement._distribute_ratios(
                [1.0] * len(participants))
            participants.write({'x_ratio_locked': False})
            for participant, ratio in zip(participants, ratios):
                # skip flag: rows land one by one on their way to an
                # equal split summing to exactly 100
                participant.with_context(
                    sn_wsd_skip_ratio_check=True).write(
                    {'performance_ratio': ratio})

    def action_reuse_last_allocation(self):
        """Reset the allocation to the one carried by the last report of
        this operation (no team fallback here)."""
        for line in self:
            if not line.mes_order_id or not line.route_operation_id:
                raise UserError(_('Select a MES order and an operation first.'))
            Report = self.env['sn.wsd.mes.operation.report'].sudo()
            last = Report.search([
                ('mes_order_id', '=', line.mes_order_id.id),
                ('route_operation_id', '=', line.route_operation_id.id),
                ('participant_ids', '!=', False),
            ], order='id desc', limit=1)
            if not last:
                raise UserError(_(
                    'No previous allocation exists for this operation.'))
            line.team_id = last.team_id.id
            line.participant_ids = [(0, 0, {
                'employee_id': p.employee_id.id,
                'performance_ratio': p.performance_ratio,
                'x_ratio_locked': False,
                'sequence': p.sequence,
            }) for p in last.participant_ids.sorted('sequence')]

    # ------------------------------------------------------------------
    # submit validation (whole batch, before anything lands)
    # ------------------------------------------------------------------

    def _validate_for_submit(self):
        self.ensure_one()
        if not self.mes_order_id or not self.route_operation_id:
            raise ValidationError(_(
                'Select a MES order and an operation on every line.'))
        if self.qty_ok < 0 or self.qty_ng < 0 or self.qty_scrap < 0:
            raise ValidationError(_('Reported quantities cannot be negative.'))
        if self.qty_ok + self.qty_ng + self.qty_scrap <= 0:
            raise ValidationError(_('Report at least one positive quantity.'))
        if self.qty_scrap > 0 and not self.scrap_reason_id:
            raise ValidationError(_(
                'Select a scrap reason when the scrap quantity is positive.'))
        # report-daily-price-inline: an OK line must be priced -- from the
        # rate table or typed on the spot (created at submit). Pure NG/scrap
        # lines generate no piece settlement and stay out of scope.
        if self.qty_ok > 0 and self.piece_price <= 0 and self.x_new_price <= 0:
            raise ValidationError(_(
                'No piece rate is configured for product %(product)s on '
                'operation %(operation)s: enter the unit price on the line '
                'before submitting.', product=self.mes_order_id.product_id
                .display_name,
                operation=self.route_operation_id.display_label))
        # enforce=True: participants are checked for every OK line, whether
        # the price comes from the rate table or is being typed right now
        self.env['sn.wsd.mes.operation.report']._check_allocation_required(
            self.mes_order_id.company_id,
            self.mes_order_id.product_id,
            self.route_operation_id.operation_id,
            self.qty_ok,
            [(p.employee_id, p.performance_ratio)
             for p in self.participant_ids],
            enforce=True)


class PieceReportWizardParticipant(models.TransientModel):
    """日报工行参与人：员工 + 绩效比（提交时原样落到报工行）。"""
    _name = 'sn.wsd.piece.report.wizard.participant'
    _description = 'Daily Reporting Wizard Participant'
    _order = 'line_id, sequence, id'

    line_id = fields.Many2one(
        'sn.wsd.piece.report.wizard.line', required=True, ondelete='cascade',
        index=True)
    sequence = fields.Integer(default=10)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        domain="['|', ('company_id', '=', False), "
               "('company_id', '=', company_id)]")
    company_id = fields.Many2one(
        'res.company', related='line_id.company_id')
    employee_code = fields.Char(
        related='employee_id.barcode', string='Employee Code')
    performance_ratio = fields.Float(
        string='Performance Ratio', digits=(12, 4), required=True,
        default=0.0)
    x_ratio_locked = fields.Boolean(
        string='Ratio Locked',
        help='Explicit lock (user decision 2026-11-01): locked rows keep '
             'their ratio when the rest is redistributed -- toggling a '
             'lock, Equal Split and Fill From Team are the only actions '
             'that re-split; typing or adding/removing rows never does.')

    @api.constrains('performance_ratio')
    def _check_ratio_total(self):
        """Immediate guard (user request 2026-11-01): a typed ratio must
        stay within 0-100 and the line total may never exceed 100% --
        no waiting for the submit gate. Redistribution helpers set the
        context flag because they write rows one by one on their way to
        an end state that sums to (at most) 100."""
        if self.env.context.get('sn_wsd_skip_ratio_check'):
            return
        for participant in self:
            ratio = participant.performance_ratio
            if ratio < 0 or ratio > 100:
                raise ValidationError(_(
                    'The performance ratio of %(employee)s must be between '
                    '0 and 100.', employee=participant.employee_id.name))
            line = participant.line_id
            total = sum(line.participant_ids.mapped('performance_ratio'))
            if total > 100 + 0.01:
                raise ValidationError(_(
                    'The ratio total of this batch cannot exceed 100%% '
                    '(currently %(total)s%%).', total=round(total, 4)))

    @api.onchange('employee_id')
    def _onchange_employee_id_default_ratio(self):
        """Non-team ad-hoc addition defaults to an equal share of the
        current headcount; ratios stay editable and the 100% total is
        enforced at submit."""
        if self.employee_id and not self.performance_ratio:
            others = self.line_id.participant_ids - self
            headcount = len(others) + 1
            self.performance_ratio = round(100.0 / headcount, 4)

    @api.onchange('x_ratio_locked')
    def _onchange_ratio_locked_rebalance(self):
        """Toggling a lock redistributes the unlocked rows (equal split of
        the remainder)."""
        self.line_id._rebalance_participants()
