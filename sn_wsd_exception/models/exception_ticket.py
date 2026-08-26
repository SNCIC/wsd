from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .exception_category import LEVEL_SELECTION

STATE_SELECTION = [
    ('pending', 'Pending'),
    ('processing', 'Processing'),
    ('suspended', 'Suspended'),
    ('pending_confirm', 'To Confirm'),
    ('done', 'Closed'),
    ('cancelled', 'Cancelled'),
]

PAUSE_REASON_SELECTION = [
    ('spare_part', 'Waiting Spare Part'),
    ('material', 'Waiting Material'),
    ('decision', 'Waiting Decision'),
]

ESCALATION_CONFIG_KEY = 'sn_wsd_exception.escalation_enabled'
LEVEL_LIMIT_DEFAULTS = {
    'normal': {'respond': 30, 'resolve': 240},
    'urgent': {'respond': 10, 'resolve': 60},
    'critical': {'respond': 3, 'resolve': 30},
}
LEVEL_CONFIRM_DEFAULTS = {
    'normal': False,
    'urgent': True,
    'critical': True,
}


class SnWsdExceptionTicket(models.Model):
    _name = 'sn.wsd.exception.ticket'
    _description = 'SN WSD Exception Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'reported_at desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Exception Reference',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    state = fields.Selection(
        STATE_SELECTION,
        string='Status',
        required=True,
        default='pending',
        tracking=True,
        index=True,
    )
    category_id = fields.Many2one(
        'sn.wsd.exception.category',
        string='Category',
        required=True,
        check_company=True,
        index=True,
        domain=[('parent_id', '=', False)],
        tracking=True,
    )
    subcategory_id = fields.Many2one(
        'sn.wsd.exception.category',
        string='Subcategory',
        check_company=True,
        index=True,
        domain="[('parent_id', '=', category_id)]",
    )
    level = fields.Selection(
        LEVEL_SELECTION,
        string='Level',
        required=True,
        default='normal',
        index=True,
        tracking=True,
    )
    description = fields.Text(string='Exception Description', required=True, tracking=True)
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'sn_wsd_exception_ticket_attachment_rel',
        'ticket_id',
        'attachment_id',
        string='Site Photos',
        copy=False,
    )
    production_line_id = fields.Many2one(
        'sn.mrp.production.line',
        string='Production Line',
        required=True,
        check_company=True,
        index=True,
        tracking=True,
    )
    workshop_id = fields.Many2one(
        related='production_line_id.workshop_id',
        string='Workshop',
        store=True,
        index=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        check_company=True,
        index=True,
        tracking=True,
    )
    team_id = fields.Many2one(
        'sn.wsd.exception.team',
        string='Responsible Team',
        check_company=True,
        index=True,
        tracking=True,
    )
    responsible_user_id = fields.Many2one('res.users', string='Responsible', index=True, tracking=True)
    reported_by_id = fields.Many2one('res.users', string='Reported By', index=True)
    confirm_user_id = fields.Many2one('res.users', string='Confirmed By', readonly=True, index=True)
    repeat_of_id = fields.Many2one(
        'sn.wsd.exception.ticket',
        string='Repeat Of',
        domain=[('state', '=', 'done')],
        index=True,
    )
    is_repeat = fields.Boolean(string='Is Repeat', compute='_compute_is_repeat', store=True)
    reason_id = fields.Many2one(
        'sn.wsd.exception.reason',
        string='Exception Reason',
        check_company=True,
        tracking=True,
    )
    temp_action = fields.Text(string='Temporary Action')
    root_cause = fields.Text(string='Root Cause')
    corrective_action = fields.Text(string='Corrective Action')
    downtime_minutes = fields.Integer(
        string='Downtime (minutes)',
        help='Manual downtime entry. Cannot exceed the reported-to-closed span of the ticket.',
    )
    impact_qty = fields.Float(string='Impact Quantity')
    scrap_qty = fields.Float(string='Scrap Quantity')
    rework_qty = fields.Float(string='Rework Quantity')
    reported_at = fields.Datetime(string='Reported At', default=fields.Datetime.now, readonly=True, copy=False)
    respond_at = fields.Datetime(string='Responded At', readonly=True, copy=False)
    reroute_at = fields.Datetime(string='Rerouted At', readonly=True, copy=False)
    closed_at = fields.Datetime(string='Closed At', readonly=True, copy=False)
    pause_line_ids = fields.One2many('sn.wsd.exception.ticket.pause', 'ticket_id', string='Suspensions')
    escalation_log_ids = fields.One2many('sn.wsd.exception.ticket.escalation', 'ticket_id', string='Escalation Log')
    escalation_count = fields.Integer(string='Escalation Count', compute='_compute_escalation_count', store=True)
    suspended_minutes = fields.Integer(
        string='Suspended (minutes)',
        compute='_compute_suspended_minutes',
        store=True,
    )
    response_minutes = fields.Integer(string='Response (minutes)', compute='_compute_durations', store=True)
    mttr_minutes = fields.Integer(string='MTTR (minutes)', compute='_compute_durations', store=True)
    is_overdue = fields.Boolean(string='Overdue', compute='_compute_is_overdue')

    @api.depends('repeat_of_id')
    def _compute_is_repeat(self):
        for ticket in self:
            ticket.is_repeat = bool(ticket.repeat_of_id)

    @api.depends('escalation_log_ids')
    def _compute_escalation_count(self):
        for ticket in self:
            ticket.escalation_count = len(ticket.escalation_log_ids)

    @api.depends('pause_line_ids.started_at', 'pause_line_ids.ended_at')
    def _compute_suspended_minutes(self):
        now = fields.Datetime.now()
        for ticket in self:
            total = 0.0
            for pause in ticket.pause_line_ids:
                end = pause.ended_at or now
                if pause.started_at:
                    total += (end - pause.started_at).total_seconds() / 60.0
            ticket.suspended_minutes = int(total)

    @api.depends('reported_at', 'respond_at', 'closed_at', 'suspended_minutes')
    def _compute_durations(self):
        for ticket in self:
            ticket.response_minutes = (
                int((ticket.respond_at - ticket.reported_at).total_seconds() // 60)
                if ticket.respond_at and ticket.reported_at else 0
            )
            if ticket.closed_at and ticket.reported_at:
                total = int((ticket.closed_at - ticket.reported_at).total_seconds() // 60)
                ticket.mttr_minutes = max(total - ticket.suspended_minutes, 0)
            else:
                ticket.mttr_minutes = 0

    def _compute_is_overdue(self):
        limits = self._level_limits()
        now = fields.Datetime.now()
        for ticket in self:
            ticket.is_overdue = False
            if ticket.state not in ('pending', 'processing'):
                continue
            limit_key = 'respond' if ticket.state == 'pending' else 'resolve'
            limit = limits.get(ticket.level, {}).get(limit_key, 0)
            anchor = ticket.reroute_at or ticket.reported_at
            if not anchor or not limit:
                continue
            elapsed = (now - anchor).total_seconds() / 60.0 - (ticket.suspended_minutes if ticket.state == 'processing' else 0.0)
            ticket.is_overdue = elapsed > limit

    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id:
            self.team_id = self.category_id.default_team_id
            self.level = self.category_id.default_level or 'normal'
            if self.subcategory_id and self.subcategory_id.parent_id != self.category_id:
                self.subcategory_id = False

    @api.onchange('production_line_id')
    def _onchange_production_line_id(self):
        if self.mes_order_id and self.mes_order_id.production_line_id != self.production_line_id:
            self.mes_order_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.exception.ticket') or _('New')
            category = False
            if vals.get('category_id'):
                category = self.env['sn.wsd.exception.category'].browse(vals['category_id']).exists()
            if category:
                if not vals.get('team_id') and category.default_team_id:
                    vals['team_id'] = category.default_team_id.id
                if not vals.get('level') and category.default_level:
                    vals['level'] = category.default_level
        tickets = super().create(vals_list)
        tickets._notify_routed()
        return tickets

    def write(self, vals):
        result = super().write(vals)
        if 'category_id' in vals:
            rerouted = self.filtered(lambda t: t.state not in ('done', 'cancelled'))
            for ticket in rerouted:
                defaults = {'reroute_at': fields.Datetime.now()}
                if ticket.category_id.default_team_id and ticket.team_id != ticket.category_id.default_team_id:
                    defaults['team_id'] = ticket.category_id.default_team_id.id
                if ticket.category_id.default_level and ticket.level != ticket.category_id.default_level:
                    defaults['level'] = ticket.category_id.default_level
                if ticket.subcategory_id and ticket.subcategory_id.parent_id != ticket.category_id:
                    defaults['subcategory_id'] = False
                ticket.with_context(skip_exception_notify=True).write(defaults)
            rerouted._notify_routed()
        return result

    @api.constrains('downtime_minutes')
    def _check_downtime_minutes(self):
        for ticket in self:
            if ticket.downtime_minutes and ticket.downtime_minutes < 0:
                raise ValidationError(_('The downtime cannot be negative.'))
            if (
                ticket.state == 'done'
                and ticket.downtime_minutes
                and ticket.closed_at
                and ticket.reported_at
            ):
                span = int((ticket.closed_at - ticket.reported_at).total_seconds() // 60)
                if ticket.downtime_minutes > span:
                    raise ValidationError(_(
                        'The downtime (%(downtime)s min) cannot exceed the reported-to-closed span (%(span)s min).',
                        downtime=ticket.downtime_minutes,
                        span=span,
                    ))

    @api.constrains('subcategory_id', 'category_id')
    def _check_subcategory_parent(self):
        for ticket in self:
            if ticket.subcategory_id and ticket.subcategory_id.parent_id != ticket.category_id:
                raise ValidationError(_('The subcategory must belong to the selected category.'))

    @api.ondelete(at_uninstall=False)
    def _unlink_only_cancelled(self):
        if any(ticket.state != 'cancelled' for ticket in self):
            raise UserError(_('Only cancelled exception tickets can be deleted.'))

    # ------------------------------------------------------------------
    # Routing and notification
    # ------------------------------------------------------------------

    def _line_leader_user(self):
        self.ensure_one()
        teams = self.env['sn.mrp.team'].search([
            ('production_line_id', '=', self.production_line_id.id),
            ('active', '=', True),
        ], order='sequence, id')
        for team in teams:
            member = team.leader_member_id
            user = member.employee_id.user_id if member else self.env['res.users']
            if user and user.active:
                return user
        return self.env['res.users']

    def _route_partner_ids(self):
        self.ensure_one()
        partners = self.env['res.partner']
        if self.team_id:
            partners |= self.team_id.member_ids.filtered(
                lambda user: user.active and user.partner_id
            ).mapped('partner_id')
        leader = self._line_leader_user()
        if leader and leader.partner_id:
            partners |= leader.partner_id
        return partners

    def _notify_routed(self):
        for ticket in self:
            if self.env.context.get('skip_exception_notify'):
                continue
            partners = ticket._route_partner_ids()
            if partners:
                ticket.message_notify(
                    partner_ids=partners.ids,
                    subject=_('MES exception %(name)s: %(category)s', name=ticket.name, category=ticket.category_id.display_name),
                    body=_(
                        'New MES exception on line %(line)s (level %(level)s): %(description)s',
                        line=ticket.production_line_id.display_name,
                        level=_(dict(LEVEL_SELECTION).get(ticket.level, ticket.level)),
                        description=ticket.description or '',
                    ),
                )
            ticket.message_post(body=_(
                'Exception routed to team %(team)s.',
                team=ticket.team_id.display_name if ticket.team_id else _('no team configured'),
            ))

    # ------------------------------------------------------------------
    # State machine actions
    # ------------------------------------------------------------------

    def action_claim(self):
        for ticket in self:
            if ticket.state != 'pending':
                raise UserError(_('Only pending exception tickets can be claimed.'))
            ticket.write({
                'state': 'processing',
                'responsible_user_id': self.env.user.id,
                'respond_at': ticket.respond_at or fields.Datetime.now(),
            })
            ticket.message_post(body=_('Exception claimed by %(user)s.', user=self.env.user.name))
        return True

    def action_suspend(self, reason):
        for ticket in self:
            if ticket.state != 'processing':
                raise UserError(_('Only in-progress exception tickets can be suspended.'))
            if reason not in dict(PAUSE_REASON_SELECTION):
                raise UserError(_('A valid suspension reason is required.'))
            self.env['sn.wsd.exception.ticket.pause'].create({
                'ticket_id': ticket.id,
                'started_at': fields.Datetime.now(),
                'reason': reason,
            })
            ticket.state = 'suspended'
            ticket.message_post(body=_(
                'Exception suspended (%(reason)s).',
                reason=_(dict(PAUSE_REASON_SELECTION).get(reason, reason)),
            ))
        return True

    def action_resume(self):
        for ticket in self:
            if ticket.state != 'suspended':
                raise UserError(_('Only suspended exception tickets can be resumed.'))
            now = fields.Datetime.now()
            for pause in ticket.pause_line_ids.filtered(lambda line: not line.ended_at):
                pause.ended_at = now
            ticket.state = 'processing'
            ticket.message_post(body=_('Exception resumed.'))
        return True

    def _closure_missing_fields(self):
        self.ensure_one()
        required = [
            ('reason_id', _('Exception Reason')),
            ('temp_action', _('Temporary Action')),
            ('root_cause', _('Root Cause')),
            ('corrective_action', _('Corrective Action')),
        ]
        return [label for fname, label in required if not self[fname]]

    def _level_needs_confirm(self):
        self.ensure_one()
        key = f'sn_wsd_exception.level_{self.level}_need_confirm'
        # get_param defaults to False for missing keys; use None as the
        # "never configured" sentinel so design defaults still apply.
        raw = self.env['ir.config_parameter'].sudo().get_param(key, default=None)
        if raw is None:
            return LEVEL_CONFIRM_DEFAULTS.get(self.level, False)
        return raw in (True, 'True', 'true', '1')

    def action_submit_close(self):
        for ticket in self:
            if ticket.state not in ('processing', 'suspended'):
                raise UserError(_('Only in-progress or suspended exception tickets can be submitted for closure.'))
            missing = ticket._closure_missing_fields()
            if missing:
                raise ValidationError(_(
                    'The following fields are required before closure: %(fields)s',
                    fields=', '.join(missing),
                ))
            now = fields.Datetime.now()
            if ticket.state == 'suspended':
                for pause in ticket.pause_line_ids.filtered(lambda line: not line.ended_at):
                    pause.ended_at = now
            if ticket._level_needs_confirm():
                ticket.state = 'pending_confirm'
                ticket.message_post(body=_('Exception submitted for closure confirmation.'))
                # the reporter confirms their own ticket (PDA card); the
                # line leader and team leader stay cc'd as fallback
                partners = ticket._line_leader_user().partner_id
                if ticket.team_id and ticket.team_id.leader_id and ticket.team_id.leader_id.partner_id:
                    partners |= ticket.team_id.leader_id.partner_id
                if ticket.create_uid and ticket.create_uid.partner_id:
                    partners |= ticket.create_uid.partner_id
                partners = partners.filtered(lambda partner: partner)
                if partners:
                    ticket.message_notify(
                        partner_ids=partners.ids,
                        subject=_('MES exception %(name)s awaits closure confirmation', name=ticket.name),
                        body=_('Please review the root cause and losses before confirming the closure.'),
                    )
            else:
                ticket.write({
                    'state': 'done',
                    'closed_at': now,
                    'confirm_user_id': self.env.user.id,
                })
                ticket.message_post(body=_('Exception closed by %(user)s.', user=self.env.user.name))
        return True

    def action_confirm(self):
        for ticket in self:
            if ticket.state != 'pending_confirm':
                raise UserError(_('Only exception tickets awaiting confirmation can be confirmed.'))
            ticket.write({
                'state': 'done',
                'closed_at': fields.Datetime.now(),
                'confirm_user_id': self.env.user.id,
            })
            ticket.message_post(body=_('Closure confirmed by %(user)s.', user=self.env.user.name))
        return True

    def action_reject(self, note):
        for ticket in self:
            if ticket.state != 'pending_confirm':
                raise UserError(_('Only exception tickets awaiting confirmation can be rejected.'))
            if not note:
                raise UserError(_('A rejection note is required.'))
            ticket.state = 'processing'
            ticket.message_post(body=_(
                'Closure rejected by %(user)s: %(note)s',
                user=self.env.user.name,
                note=note,
            ))
        return True

    def action_cancel(self, note=False):
        for ticket in self:
            if ticket.state == 'done':
                raise UserError(_('Closed exception tickets cannot be cancelled.'))
            now = fields.Datetime.now()
            for pause in ticket.pause_line_ids.filtered(lambda line: not line.ended_at):
                pause.ended_at = now
            ticket.state = 'cancelled'
            ticket.message_post(body=_(
                'Exception cancelled by %(user)s. Note: %(note)s',
                user=self.env.user.name,
                note=note or '',
            ))
        return True

    # ------------------------------------------------------------------
    # Wizard launchers
    # ------------------------------------------------------------------

    def _open_wizard(self, wizard_model, default_note=''):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Exception Ticket'),
            'res_model': wizard_model,
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id},
        }

    def action_open_suspend_wizard(self):
        return self._open_wizard('sn.wsd.exception.suspend.wizard')

    def action_open_reject_wizard(self):
        return self._open_wizard('sn.wsd.exception.reject.wizard')

    def action_open_cancel_wizard(self):
        return self._open_wizard('sn.wsd.exception.cancel.wizard')

    def action_open_repeat_candidates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Repeat Candidates'),
            'res_model': 'sn.wsd.exception.ticket',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'done'),
                ('production_line_id', '=', self.production_line_id.id),
                ('category_id', '=', self.category_id.id),
                ('reported_at', '>=', fields.Datetime.now() - timedelta(days=7)),
            ],
            'context': {'default_repeat_of_id': self.id},
        }

    # ------------------------------------------------------------------
    # Escalation cron
    # ------------------------------------------------------------------

    @api.model
    def _level_limits(self):
        icp = self.env['ir.config_parameter'].sudo()

        def minutes(key, default):
            raw = icp.get_param(key)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return default
            return value if value > 0 else default

        return {
            level: {
                'respond': minutes(f'sn_wsd_exception.respond_{level}', values['respond']),
                'resolve': minutes(f'sn_wsd_exception.resolve_{level}', values['resolve']),
            }
            for level, values in LEVEL_LIMIT_DEFAULTS.items()
        }

    def _escalation_target_user(self, stage):
        self.ensure_one()
        if stage <= 1:
            return self._line_leader_user()
        company = self.company_id
        if stage == 2:
            return company.exception_supervisor_user_id
        return company.exception_manager_user_id

    @api.model
    def cron_escalate(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(ESCALATION_CONFIG_KEY)
        if raw not in (True, 'True', 'true', '1'):
            return
        limits = self._level_limits()
        now = fields.Datetime.now()
        tickets = self.search([('state', 'in', ('pending', 'processing'))])
        for ticket in tickets:
            limit_key = 'respond' if ticket.state == 'pending' else 'resolve'
            limit = limits.get(ticket.level, {}).get(limit_key)
            anchor = ticket.reroute_at or ticket.reported_at
            if not limit or not anchor:
                continue
            elapsed = (now - anchor).total_seconds() / 60.0
            if ticket.state == 'processing':
                elapsed -= ticket.suspended_minutes
            stage = ticket.escalation_count
            if elapsed < limit * (stage + 1):
                continue
            target = ticket._escalation_target_user(stage + 1)
            self.env['sn.wsd.exception.ticket.escalation'].create({
                'ticket_id': ticket.id,
                'escalated_at': now,
                'stage': stage + 1,
                'user_id': target.id if target else False,
            })
            if target and target.partner_id:
                ticket.message_notify(
                    partner_ids=target.partner_id.ids,
                    subject=_('MES exception %(name)s escalated (stage %(stage)s)', name=ticket.name, stage=stage + 1),
                    body=_(
                        'Exception on line %(line)s is overdue and has been escalated. Please follow up.',
                        line=ticket.production_line_id.display_name,
                    ),
                )
            ticket.message_post(body=_(
                'Exception escalated to stage %(stage)s (%(user)s).',
                stage=stage + 1,
                user=target.name if target else _('no target configured'),
            ))
