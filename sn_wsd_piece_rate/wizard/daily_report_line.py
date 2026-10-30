from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

ACTIVE_REPORT_STATES = ('released', 'picked', 'in_progress')


class PieceReportWizardLine(models.TransientModel):
    """日报工·待报工页签的行（report-daily-workbench）。

    一行 = 一个活跃报工单（report 模式、released/picked/in_progress）
    私有路线上的一道工序：录 OK/NG/报废三数量、报废原因、班组与参与人，
    展示 计划量/已报/可报额度 与顺序锁状态。提交由向导的
    action_submit_reports 在一个事务内逐行调 report_operation_qty。
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
    team_id = fields.Many2one(
        'sn.mrp.team', string='Team',
        check_company=True,
        domain="[('production_line_id', '=', production_line_id)]",
        help='Team used to pre-fill participants and their performance '
             'ratios (normalized over the participating subset).')
    participant_ids = fields.One2many(
        'sn.wsd.piece.report.wizard.participant', 'line_id',
        string='Participants')
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

    @api.depends('participant_ids.employee_id', 'participant_ids.performance_ratio')
    def _compute_participants(self):
        for line in self:
            line.participant_count = len(line.participant_ids)
            line.participant_summary = ' / '.join(
                f'{p.employee_id.name} {p.performance_ratio:g}%'
                for p in line.participant_ids.sorted('sequence'))

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

    # ------------------------------------------------------------------
    # quick-fill buttons (same calibers as the settlement form)
    # ------------------------------------------------------------------

    def action_fill_from_team(self):
        Settlement = self.env['sn.wsd.piece.settlement']
        for line in self:
            if not line.team_id:
                raise UserError(_('Select a team first.'))
            members = line.team_id.member_ids
            if not members:
                raise UserError(_('The team has no members.'))
            ratios = Settlement._distribute_ratios(
                members.mapped('performance_ratio'))
            line.participant_ids = [fields.Command.clear()] + [
                fields.Command.create({
                    'employee_id': member.employee_id.id,
                    'performance_ratio': ratio,
                    'sequence': 10 * (index + 1),
                }) for index, (member, ratio) in enumerate(
                    zip(members, ratios))]

    def action_equal_split(self):
        Settlement = self.env['sn.wsd.piece.settlement']
        for line in self:
            participants = line.participant_ids.sorted('sequence')
            if not participants:
                raise UserError(_('Add participants first.'))
            ratios = Settlement._distribute_ratios(
                [1.0] * len(participants))
            for participant, ratio in zip(participants, ratios):
                participant.performance_ratio = ratio

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
        self.env['sn.wsd.mes.operation.report']._check_allocation_required(
            self.mes_order_id.company_id,
            self.mes_order_id.product_id,
            self.route_operation_id.operation_id,
            self.qty_ok,
            [(p.employee_id, p.performance_ratio)
             for p in self.participant_ids])


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

    @api.onchange('employee_id')
    def _onchange_employee_id_default_ratio(self):
        """Non-team ad-hoc addition defaults to an equal share of the
        current headcount; ratios stay editable and the 100% total is
        enforced at submit."""
        if self.employee_id and not self.performance_ratio:
            others = self.line_id.participant_ids - self
            headcount = len(others) + 1
            self.performance_ratio = round(100.0 / headcount, 4)
