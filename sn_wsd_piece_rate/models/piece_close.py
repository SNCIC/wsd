import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PERIOD_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


class SnWsdPieceCloseLog(models.Model):
    """月度关账事件流水：生效状态 = 同 (公司, 月份) 最新事件。

    close 后该月不可新增计件单、不可确认草稿、不可作废；
    reopen（月初重算）重新放行，两者均留痕。
    """
    _name = 'sn.wsd.piece.close.log'
    _description = 'Piece Rate Monthly Close Log'
    _order = 'period desc, at desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company, required=True, index=True)
    period = fields.Char(
        string='Period', required=True, index=True,
        help='Business-date month (YYYY-MM) the close applies to.')
    action = fields.Selection(
        [('close', 'Close'), ('reopen', 'Reopen')],
        string='Action', required=True)
    user_id = fields.Many2one(
        'res.users', string='User', default=lambda self: self.env.user)
    at = fields.Datetime(string='Executed At', default=fields.Datetime.now)
    draft_count = fields.Integer(
        string='Remaining Drafts',
        help='Draft settlements in the period when the event was logged.')

    _period_format = models.Constraint(
        "CHECK(period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$')",
        'The period must be formatted YYYY-MM.',
    )

    @api.model
    def _period_of(self, date):
        return date.strftime('%Y-%m') if date else None

    @api.model
    def _month_closed(self, company, date):
        """True when the latest event for the period is a close."""
        period = self._period_of(date)
        if not period:
            return False
        last = self.sudo().search([
            ('company_id', '=', company.id),
            ('period', '=', period),
        ], order='at desc, id desc', limit=1)
        return bool(last) and last.action == 'close'

    @api.model
    def _assert_month_open(self, company, date):
        if self._month_closed(company, date):
            raise UserError(_(
                'Period %s is closed. Reopen it first (a piece-rate manager '
                'can reopen for month-start recalculation).',
                self._period_of(date)))


class PieceCloseWizard(models.TransientModel):
    """月度关账向导：公司+月份；执行前展示该月剩余草稿数，操作人勾选确认后才执行。"""
    _name = 'sn.wsd.piece.close.wizard'
    _description = 'Piece Rate Monthly Close Wizard'

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company, required=True)
    period = fields.Char(
        string='Period', required=True,
        help='Business-date month to close, formatted YYYY-MM.')
    draft_count = fields.Integer(
        string='Remaining Drafts', compute='_compute_draft_count')
    acknowledge_drafts = fields.Boolean(
        string='Acknowledge Remaining Drafts',
        help='Check to confirm you are aware unsettled drafts stay in the '
             'closed period.')

    @api.depends('company_id', 'period')
    def _compute_draft_count(self):
        for wizard in self:
            wizard.draft_count = wizard._search_drafts_count()

    def _search_drafts_count(self):
        self.ensure_one()
        if not self.period or not PERIOD_RE.match(self.period):
            return 0
        year, month = map(int, self.period.split('-'))
        date_from = fields.Date.to_date(f'{year:04d}-{month:02d}-01')
        date_to = fields.Date.end_of(date_from, 'month')
        return self.env['sn.wsd.piece.settlement'].search_count([
            ('company_id', '=', self.company_id.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('state', '=', 'draft'),
        ])

    def action_close(self):
        self._ensure_manager()
        self._validate_period()
        if self.draft_count and not self.acknowledge_drafts:
            raise UserError(_(
                'The period still has %(count)s draft settlement(s). Confirm '
                'them first or acknowledge to close anyway.',
                count=self.draft_count))
        self.env['sn.wsd.piece.close.log'].create({
            'company_id': self.company_id.id,
            'period': self.period,
            'action': 'close',
            'draft_count': self.draft_count,
        })
        return self._reload_action()

    def action_reopen(self):
        self._ensure_manager()
        self._validate_period()
        self.env['sn.wsd.piece.close.log'].create({
            'company_id': self.company_id.id,
            'period': self.period,
            'action': 'reopen',
        })
        return self._reload_action()

    def _ensure_manager(self):
        if not self.env.user.has_group('sn_wsd_piece_rate.group_piece_rate_manager'):
            raise UserError(_('Only piece-rate managers can close or reopen periods.'))

    def _validate_period(self):
        for wizard in self:
            if not PERIOD_RE.match(wizard.period or ''):
                raise ValidationError(_('The period must be formatted YYYY-MM.'))

    def _reload_action(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Monthly Closing'),
            'res_model': 'sn.wsd.piece.close.log',
            'view_mode': 'list',
        }
