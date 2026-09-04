from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SnWsdPieceSettlement(models.Model):
    _name = 'sn.wsd.piece.settlement'
    _description = 'Piece Rate Settlement'
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', copy=False, default=lambda self: _('New'))
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed'), ('void', 'Void')],
        string='Status',
        default='draft',
        required=True,
        index=True,
        copy=False,
    )
    date = fields.Date(
        string='Business Date',
        default=fields.Date.context_today,
        required=True,
        help='Ledger month and monthly closing follow this date, not the '
             'creation date (late settlements are back-dated).',
    )
    company_id = fields.Many2one(
        'res.company', related='mes_order_id.company_id', store=True, index=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True,
        index=True, ondelete='restrict')
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Operation', required=True,
        index=True, ondelete='restrict',
        domain="[('mes_order_id', '=', mes_order_id)]")
    manage_mode = fields.Selection(
        related='mes_order_id.x_manage_mode', string='Manage Mode', store=True)
    product_id = fields.Many2one(
        related='mes_order_id.product_id', string='Product', store=True)
    operation_id = fields.Many2one(
        related='route_operation_id.operation_id', string='Operation (Dict)',
        store=True)
    workshop_id = fields.Many2one(
        related='mes_order_id.x_workshop_id', store=True, index=True)
    production_line_id = fields.Many2one(
        related='mes_order_id.production_line_id', store=True, index=True)
    operation_report_id = fields.Many2one(
        'sn.wsd.mes.operation.report', string='Operation Report',
        index=True, ondelete='restrict', copy=False)
    serial_identity_ids = fields.Many2many(
        'sn.wsd.serial.identity',
        'sn_wsd_piece_settlement_serial_rel',
        'settlement_id', 'serial_identity_id',
        string='Covered Serials',
        copy=False,
        help='SNs whose first OK pass at this operation is paid by this '
             'settlement (station mode). Voiding releases them.',
    )
    qty_ok = fields.Float(string='OK Quantity', digits='Product Unit of Measure', copy=False)
    price = fields.Float(
        string='Price Snapshot', digits=(12, 5), copy=False,
        help='Unit price resolved from the rate table when the settlement '
             'was sourced. Later rate changes do not affect it.')
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', store=True)
    amount = fields.Monetary(string='Amount', compute='_compute_amount', store=True)
    team_id = fields.Many2one(
        'sn.mrp.team', string='Team',
        check_company=True,
        domain="[('production_line_id', '=', production_line_id)]",
        help='Team used to pre-fill participants and their performance '
             'ratios (normalized over the participating subset).')
    participant_ids = fields.One2many(
        'sn.wsd.piece.settlement.participant', 'settlement_id',
        string='Participants', copy=True)
    participant_count = fields.Integer(compute='_compute_participant_count')
    ratio_total = fields.Float(
        string='Ratio Total', compute='_compute_ratio_total',
        help='Sum of participant performance ratios; must be 100%.')
    allocated_total = fields.Monetary(
        string='Allocated Total', compute='_compute_allocated_total',
        help='Sum of allocated amounts. May be a few cents below the '
             'settlement amount: rounding remainders are dropped.')
    voided_by = fields.Many2one('res.users', string='Voided By', readonly=True, copy=False)
    voided_at = fields.Datetime(string='Voided On', readonly=True, copy=False)
    month_closed = fields.Boolean(
        string='Month Closed', compute='_compute_month_closed',
        help='The business-date month is closed: no new settlements, no '
             'confirming, no voiding until a manager reopens it.')

    @api.depends('company_id', 'date')
    def _compute_month_closed(self):
        CloseLog = self.env['sn.wsd.piece.close.log']
        for settlement in self:
            settlement.month_closed = CloseLog._month_closed(
                settlement.company_id, settlement.date)

    @api.depends('qty_ok', 'price')
    def _compute_amount(self):
        for settlement in self:
            settlement.amount = round(settlement.qty_ok * settlement.price, 2)

    @api.depends('participant_ids')
    def _compute_participant_count(self):
        for settlement in self:
            settlement.participant_count = len(settlement.participant_ids)

    @api.depends('participant_ids.performance_ratio')
    def _compute_ratio_total(self):
        for settlement in self:
            settlement.ratio_total = round(
                sum(settlement.participant_ids.mapped('performance_ratio')), 4)

    @api.depends('participant_ids.amount')
    def _compute_allocated_total(self):
        for settlement in self:
            settlement.allocated_total = sum(
                settlement.participant_ids.mapped('amount'))

    @api.onchange('participant_ids')
    def _onchange_participant_ids_rebalance(self):
        """手改即锁定：改过绩效比的行（值≠基线）保持不动，
        其余行按各自基线权重分摊剩余比例（基线合计≤0 退化为均分），
        末行吸收舍入尾差；锁定行合计>100% 时不自动改（确认校验拦截）。

        不变量：auto 行重分后基线同步改写为当前值（auto 集合内部
        权重比例保持不变，重写不改变后续分摊结果），因此
        "值==基线" 恒等于 "未被手改"。"""
        for settlement in self:
            lines = settlement.participant_ids
            if not lines:
                continue
            manual = lines.filtered(
                lambda l: abs(l.performance_ratio - l.x_ratio_baseline) > 0.0001)
            auto = lines - manual
            if not auto:
                continue
            manual_total = sum(manual.mapped('performance_ratio'))
            remaining = 100.0 - manual_total
            if remaining < -0.01:
                continue
            auto_lines = list(auto)
            weights = [l.x_ratio_baseline for l in auto_lines]
            weight_total = sum(weights)
            if weight_total <= 0:
                weights = [1.0] * len(auto_lines)
                weight_total = float(len(auto_lines))
            for i, line in enumerate(auto_lines):
                if i < len(auto_lines) - 1:
                    line.performance_ratio = round(
                        remaining * weights[i] / weight_total, 4)
                else:
                    line.performance_ratio = round(
                        100.0 - manual_total - sum(
                            l.performance_ratio for l in auto_lines[:-1]), 4)
                line.x_ratio_baseline = line.performance_ratio

    @api.constrains('participant_ids', 'participant_ids.performance_ratio')
    def _check_ratio_total(self):
        # 草稿期自由编辑（逐行加人时合计必然中途不等于100）；
        # 确认动作（action_confirm）在置 state=confirmed 前先行校验，
        # 本约束兜底已确认单据不得写出坏比例。
        for settlement in self:
            if settlement.state == 'confirmed' and settlement.participant_ids \
                    and abs(settlement.ratio_total - 100.0) > 0.01:
                raise ValidationError(_(
                    'The total performance ratio of participants must be 100%.'))

    @api.model_create_multi
    def create(self, vals_list):
        CloseLog = self.env['sn.wsd.piece.close.log']
        company_cache = {}
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.piece.settlement') or _('New')
            date = vals.get('date') or fields.Date.context_today(self)
            if vals.get('company_id'):
                company = self.env['res.company'].browse(vals['company_id'])
            elif vals.get('mes_order_id'):
                company = self.env['sn.wsd.mes.order'].browse(
                    vals['mes_order_id']).company_id or self.env.company
            else:
                company = self.env.company
            CloseLog._assert_month_open(company, date)
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # state machine: confirm freeze / void release
    # ------------------------------------------------------------------

    _FREEZE_ALLOWED_FIELDS = {'state', 'voided_by', 'voided_at'}

    def write(self, vals):
        blocked = set(vals) - self._FREEZE_ALLOWED_FIELDS
        if blocked:
            for settlement in self:
                if settlement.state != 'draft':
                    raise UserError(_(
                        'Settlement %s is confirmed: its people, quantities, '
                        'price and business date are frozen. Void it to '
                        'release the source and settle again.',
                        settlement.name))
        if 'date' in vals:
            CloseLog = self.env['sn.wsd.piece.close.log']
            for settlement in self:
                if settlement.state == 'draft':
                    CloseLog._assert_month_open(settlement.company_id, vals['date'])
        return super().write(vals)

    def action_confirm(self):
        CloseLog = self.env['sn.wsd.piece.close.log']
        for settlement in self:
            if settlement.state != 'draft':
                raise UserError(_('Only draft settlements can be confirmed.'))
            if not settlement.participant_ids:
                raise ValidationError(_(
                    'Add at least one participant before confirming.'))
            if abs(settlement.ratio_total - 100.0) > 0.01:
                raise ValidationError(_(
                    'The total performance ratio of participants must be 100%.'))
            if settlement.qty_ok <= 0:
                raise ValidationError(_(
                    'The OK quantity must be greater than zero.'))
            if settlement.price <= 0:
                raise ValidationError(_(
                    'Resolve the piece rate before confirming.'))
            settlement._validate_source()
            CloseLog._assert_month_open(settlement.company_id, settlement.date)
        self.write({'state': 'confirmed'})
        return True

    def action_void(self):
        if not self.env.user.has_group(
                'sn_wsd_piece_rate.group_piece_rate_manager'):
            raise UserError(_('Only piece-rate managers can void settlements.'))
        CloseLog = self.env['sn.wsd.piece.close.log']
        for settlement in self:
            if settlement.state == 'void':
                raise UserError(_('Settlement %s is already void.', settlement.name))
            CloseLog._assert_month_open(settlement.company_id, settlement.date)
        self.write({
            'state': 'void',
            'voided_by': self.env.user.id,
            'voided_at': fields.Datetime.now(),
        })
        return True

    # ------------------------------------------------------------------
    # rate resolution (snapshot)
    # ------------------------------------------------------------------

    def _resolve_rate_price(self):
        """Resolve the piece rate for (company, product, operation) and
        snapshot it on the settlement. Hard-blocks when unconfigured."""
        Rate = self.env['sn.wsd.piece.rate'].sudo()
        for settlement in self:
            rate = Rate.search([
                ('company_id', '=', settlement.company_id.id),
                ('product_id', '=', settlement.product_id.id),
                ('operation_id', '=', settlement.operation_id.id),
            ], limit=1)
            if not rate:
                raise UserError(_(
                    'No piece rate is configured for product %(product)s on '
                    'operation %(operation)s. Please maintain it first.',
                    product=settlement.product_id.display_name,
                    operation=settlement.operation_id.display_name))
            settlement.price = rate.price

    @api.onchange('route_operation_id')
    def _onchange_route_operation_id_resolve_price(self):
        if self.route_operation_id and not self.price:
            self._resolve_rate_price()

    @api.onchange('mes_order_id')
    def _onchange_mes_order_id_default_team(self):
        """Pre-fill the team when the order's line has exactly one active team."""
        if self.mes_order_id and self.mes_order_id.production_line_id:
            teams = self.env['sn.mrp.team'].search([
                ('production_line_id', '=', self.mes_order_id.production_line_id.id),
                ('active', '=', True),
            ])
            if len(teams) == 1:
                self.team_id = teams.id

    # ------------------------------------------------------------------
    # report-mode source (1:1 occupancy, draft occupies, void releases)
    # ------------------------------------------------------------------

    @api.onchange('operation_report_id')
    def _onchange_operation_report_id_source(self):
        if self.operation_report_id:
            report = self.operation_report_id
            self.qty_ok = report.qty_ok
            if report.reported_at:
                self.date = report.reported_at.date()
            self._resolve_rate_price()

    @api.constrains('operation_report_id')
    def _check_report_occupancy(self):
        for settlement in self:
            if not settlement.operation_report_id:
                continue
            dup = self.search([
                ('operation_report_id', '=', settlement.operation_report_id.id),
                ('state', '!=', 'void'),
                ('id', '!=', settlement.id),
            ])
            if dup:
                raise ValidationError(_(
                    'Report %(report)s is already settled by %(settlement)s.',
                    report=settlement.operation_report_id.display_name,
                    settlement=dup[0].name))

    def _validate_source(self):
        """Confirm-time source consistency (wired in action_confirm)."""
        for settlement in self:
            if settlement.manage_mode == 'report':
                if not settlement.operation_report_id:
                    raise ValidationError(_(
                        'A report-mode settlement must reference an '
                        'operation report.'))
                if abs(settlement.qty_ok
                       - settlement.operation_report_id.qty_ok) > 0.0001:
                    raise ValidationError(_(
                        'The OK quantity must equal the referenced report '
                        'quantity.'))
            elif settlement.operation_report_id:
                raise ValidationError(_(
                    'Only report-mode settlements can reference an '
                    'operation report.'))
        self._validate_station_coverage()

    def _default_team_and_participants(self):
        """Pre-fill team + participants when the order's line has exactly
        one active team (wizard generation path)."""
        for settlement in self:
            if not settlement.production_line_id:
                continue
            teams = self.env['sn.mrp.team'].search([
                ('production_line_id', '=', settlement.production_line_id.id),
                ('active', '=', True),
            ])
            if len(teams) == 1:
                settlement.team_id = teams.id
                if teams.member_ids:
                    settlement.action_fill_from_team()

    def action_view_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Operation Report'),
            'res_model': 'sn.wsd.mes.operation.report',
            'res_id': self.operation_report_id.id,
            'view_mode': 'form',
        }

    # ------------------------------------------------------------------
    # station-mode source (unsettled balance, first-OK anchor, FIFO capture)
    # ------------------------------------------------------------------

    unsettled_qty = fields.Float(
        string='Unsettled Quantity',
        compute='_compute_unsettled_qty',
        digits='Product Unit of Measure',
        help='Station mode: SN count with a first OK pass at this operation '
             'not yet covered by any non-void settlement.')

    @api.depends('mes_order_id', 'route_operation_id')
    def _compute_unsettled_qty(self):
        for settlement in self:
            if settlement.manage_mode != 'station' or not settlement.route_operation_id:
                settlement.unsettled_qty = 0.0
                continue
            anchors = settlement._station_anchor_map()
            covered = settlement._covered_serial_ids()
            settlement.unsettled_qty = len(
                [sn for sn in anchors if sn not in covered])

    def _station_anchor_map(self):
        """SN id -> first OK out_date at this (order, operation): the anchor
        for one-pay-per-SN and FIFO capture."""
        self.ensure_one()
        self.env['sn.wsd.serial.operation.history'].flush_model(
            ['mes_order_id', 'route_operation_id', 'result', 'out_date'])
        self.env.cr.execute("""
            SELECT serial_identity_id, MIN(out_date)
            FROM sn_wsd_serial_operation_history
            WHERE mes_order_id = %s
              AND route_operation_id = %s
              AND result = 'ok'
            GROUP BY serial_identity_id
        """, (self.mes_order_id.id, self.route_operation_id.id))
        return dict(self.env.cr.fetchall())

    def _covered_serial_ids(self, confirmed_only=False):
        """SN ids covered by other settlements of this (order, operation).
        Drafts occupy for sourcing (button/unsettled balance); the
        confirm-time concurrency recheck counts confirmed settlements only
        so the first of two racing drafts can still confirm."""
        self.ensure_one()
        domain = [
            ('mes_order_id', '=', self.mes_order_id.id),
            ('route_operation_id', '=', self.route_operation_id.id),
            ('id', '!=', self.id),
        ]
        domain.append(('state', '=', 'confirmed') if confirmed_only
                      else ('state', '!=', 'void'))
        covered = set()
        for other in self.search(domain):
            covered |= set(other.serial_identity_ids.ids)
        return covered

    def action_compute_from_station(self):
        """Station mode sourcing: resolve the price snapshot and capture the
        covered SN set, FIFO by first OK out_date. The settlement quantity
        defaults to the full unsettled count and may be lowered (retroactive
        split); it can never exceed the unsettled count."""
        for settlement in self:
            if settlement.manage_mode != 'station':
                raise UserError(_(
                    'This action is only for station-mode settlements.'))
            anchors = settlement._station_anchor_map()
            covered = settlement._covered_serial_ids()
            available = sorted(
                ((sn, date) for sn, date in anchors.items() if sn not in covered),
                key=lambda item: (item[1], item[0]))
            if not available:
                raise UserError(_(
                    'No unsettled OK quantity at this operation yet.'))
            if settlement.qty_ok <= 0:
                settlement.qty_ok = float(len(available))
            if settlement.qty_ok > len(available):
                raise UserError(_(
                    'The settlement quantity (%(qty)s) exceeds the unsettled '
                    'quantity (%(available)s).',
                    qty=settlement.qty_ok, available=len(available)))
            settlement._resolve_rate_price()
            taken = [sn for sn, _ in available[:int(settlement.qty_ok)]]
            settlement.write({'serial_identity_ids': [(6, 0, taken)]})

    def _validate_station_coverage(self):
        """Confirm-time recheck: coverage present, matches the quantity, and
        no SN is claimed by another non-void settlement (concurrency guard)."""
        for settlement in self:
            if settlement.manage_mode != 'station':
                continue
            if not settlement.serial_identity_ids:
                raise ValidationError(_(
                    'A station-mode settlement must cover at least one serial.'))
            if settlement.qty_ok != len(settlement.serial_identity_ids):
                raise ValidationError(_(
                    'The OK quantity must equal the number of covered serials.'))
            clash = settlement._covered_serial_ids(
                confirmed_only=True) & set(
                settlement.serial_identity_ids.ids)
            if clash:
                raise ValidationError(_(
                    'Some serials are already covered by another settlement.'))

    # ------------------------------------------------------------------
    # participant pre-fill
    # ------------------------------------------------------------------

    @staticmethod
    def _distribute_ratios(weights):
        """Normalize weights to a list of ratios summing to exactly 100,
        keeping proportions; the last line absorbs the rounding remainder.
        Non-positive total falls back to an equal split."""
        total = sum(weights)
        if total <= 0:
            ratios = [100.0 / len(weights)] * len(weights)
        else:
            ratios = [w / total * 100.0 for w in weights]
        result = [round(r, 4) for r in ratios[:-1]]
        result.append(round(100.0 - sum(result), 4))
        return result

    def action_fill_from_team(self):
        """Fill participants from the team. Existing participants keep their
        employee: team members get their member ratio as weight, others keep
        their current ratio (or an equal share), then the whole set is
        normalized to 100%."""
        for settlement in self:
            if not settlement.team_id:
                raise UserError(_('Select a team first.'))
            members = settlement.team_id.member_ids
            if not members:
                raise UserError(_('The team has no members.'))
            ratio_by_employee = {
                m.employee_id.id: m.performance_ratio for m in members}
            employees = settlement.participant_ids.mapped('employee_id')
            if not employees:
                employees = members.mapped('employee_id')
            share = 100.0 / len(employees) if employees else 0.0
            weights = [
                ratio_by_employee.get(e.id, 0.0) or share for e in employees]
            ratios = self._distribute_ratios(weights)
            settlement.participant_ids = [
                fields.Command.clear()] + [
                fields.Command.create({
                    'employee_id': e.id,
                    'performance_ratio': r,
                    'x_ratio_baseline': r,
                }) for e, r in zip(employees, ratios)]

    def action_equal_split(self):
        for settlement in self:
            employees = settlement.participant_ids.mapped('employee_id')
            if not employees:
                raise UserError(_('Add participants first.'))
            ratios = self._distribute_ratios([1.0] * len(employees))
            settlement.participant_ids = [
                fields.Command.clear()] + [
                fields.Command.create({
                    'employee_id': e.id,
                    'performance_ratio': r,
                    'x_ratio_baseline': r,
                }) for e, r in zip(employees, ratios)]


class SnWsdPieceSettlementParticipant(models.Model):
    _name = 'sn.wsd.piece.settlement.participant'
    _description = 'Piece Rate Settlement Participant'
    _order = 'settlement_id, sequence, id'
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    settlement_id = fields.Many2one(
        'sn.wsd.piece.settlement', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', related='settlement_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(
        'res.currency', related='settlement_id.currency_id', store=True)
    settlement_date = fields.Date(
        string='Business Date', related='settlement_id.date',
        store=True, index=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order',
        related='settlement_id.mes_order_id', store=True, index=True)
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Operation',
        related='settlement_id.route_operation_id', store=True, index=True)
    workshop_id = fields.Many2one(
        'sn.mrp.workshop', string='Workshop',
        related='settlement_id.workshop_id', store=True, index=True)
    production_line_id = fields.Many2one(
        'sn.mrp.production.line', string='Production Line',
        related='settlement_id.production_line_id', store=True, index=True)
    settlement_qty_ok = fields.Float(
        string='Settlement OK Quantity',
        related='settlement_id.qty_ok', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        check_company=True, ondelete='restrict')
    employee_code = fields.Char(
        related='employee_id.barcode', string='Employee Code', store=True)
    performance_ratio = fields.Float(
        string='Performance Ratio', digits=(12, 4), required=True, default=0.0)
    x_ratio_baseline = fields.Float(
        string='Ratio Baseline', digits=(12, 4),
        help='Weight used to auto-redistribute the leftover ratio: rows the '
             'user typed over (ratio != baseline) keep their value, the rest '
             'share the remainder proportionally to their baseline.')
    amount = fields.Monetary(
        string='Allocated Amount', compute='_compute_amount', store=True)

    _participant_unique = models.Constraint(
        'unique(settlement_id, employee_id)',
        'The employee is already a participant of this settlement.',
    )
    _participant_ratio_range = models.Constraint(
        'CHECK(performance_ratio >= 0 AND performance_ratio <= 100)',
        'The performance ratio must be between 0 and 100.',
    )

    @api.depends('settlement_id.amount', 'performance_ratio')
    def _compute_amount(self):
        for participant in self:
            participant.amount = round(
                participant.settlement_id.amount
                * participant.performance_ratio / 100.0, 2)

    @api.onchange('employee_id')
    def _onchange_employee_id_default_ratio(self):
        """Non-team ad-hoc addition defaults to an equal share of the
        current headcount; ratios stay editable and the 100% total is
        enforced by the settlement constraint."""
        if self.employee_id and not self.performance_ratio:
            others = self.settlement_id.participant_ids - self
            headcount = len(others) + 1
            self.performance_ratio = round(100.0 / headcount, 4)
            self.x_ratio_baseline = self.performance_ratio
