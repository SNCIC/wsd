import json
import logging
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Namespace of the session-level advisory lock that serialises the pulls
# of one integration config (PostgreSQL takes two int4 keys).
PULL_LOCK_NAMESPACE = 0x45495031
PULL_PAGE_SIZE_CAP = 1000
PULL_MAX_PAGES = 10000
PULL_INTERFACE = 'purchase_order'


class EipConfig(models.Model):
    _inherit = 'sn.wsd.eip.config'

    @api.model_create_multi
    def create(self, vals_list):
        configs = super().create(vals_list)
        # every config gets its pull state at once so the Pull State
        # screen and its button exist as soon as the config does
        self.env['sn.wsd.eip.pull.state'].create(
            [{'config_id': config.id} for config in configs])
        return configs

    # ------------------------------------------------------------------
    # purchase-order pull engine
    # ------------------------------------------------------------------

    def _eip_pull_lock(self):
        """Session-level advisory lock per config: unlike a transaction
        lock it survives the commits of the pull loop. The caller must
        unlock in a ``finally`` block."""
        self.ensure_one()
        self.env.cr.execute(
            'SELECT pg_advisory_lock(%s, %s)', (PULL_LOCK_NAMESPACE, self.id))

    def _eip_pull_unlock(self):
        self.env.cr.execute(
            'SELECT pg_advisory_unlock(%s, %s)',
            (PULL_LOCK_NAMESPACE, self.id))

    def _eip_pull_state(self):
        self.ensure_one()
        State = self.env['sn.wsd.eip.pull.state']
        state = State.search([('config_id', '=', self.id)], limit=1)
        if not state:
            state = State.create({'config_id': self.id})
        return state

    def _eip_pull_commit(self):
        """Commit point of the pull loop.

        The one deliberate explicit commit of the module: the call
        counter and the "sending" log of a request must be durable
        before the request leaves, otherwise a failed page or a crash
        would erase calls that were really made and the daily limit
        could be exceeded. The commit empties the ORM cache, so values
        are read again from the database after it. Tests replace it
        with a flush: the test framework forbids commits.
        """
        self.env.cr.commit()

    def _eip_pull_window_start(self, state, window_end):
        """Start of a new incremental window: the watermark minus the
        overlap, else the configured first-sync start date, else None
        (no update-time condition at all: full sync)."""
        if state.watermark:
            start = state.watermark - timedelta(
                hours=self.pull_overlap_hours or 0)
        elif self.pull_start_date:
            start = self.env['sn.wsd.eip.transport']._eip_beijing_to_utc(
                datetime.combine(self.pull_start_date, datetime.min.time()))
        else:
            return None
        return min(start, window_end)

    def _eip_pull_incremental(self):
        """Incremental pull (cron and wizard): resume the unfinished
        window at its breakpoint if there is one, otherwise open a new
        frozen window. The watermark only moves once a window completes.
        Never raises for transport or platform failures."""
        self.ensure_one()
        # whoever triggers it (wizard user or cron), the engine writes
        # system state (counter, watermark, logs) that users only read
        self = self.sudo()
        self._eip_pull_lock()
        try:
            state = self._eip_pull_state()
            if state.pending_end:
                window_start = state.pending_start
                window_end = state.pending_end
                page = state.pending_page or 1
            else:
                window_end = fields.Datetime.now()
                window_start = self._eip_pull_window_start(state, window_end)
                page = 1
                # stored before the first request: a crash mid-run resumes
                # the same window instead of opening a new one
                state.write({
                    'pending_start': window_start,
                    'pending_end': window_end,
                    'pending_page': page,
                })
                self._eip_pull_commit()
            conditions = {}
            if window_start is not None:
                transport = self.env['sn.wsd.eip.transport']
                conditions = {
                    'modifyStartTime': transport._eip_format_datetime(window_start),
                    'modifyEndTime': transport._eip_format_datetime(window_end),
                }
            return self._eip_pull_pages(
                state, conditions, page, window_end, advance=True)
        finally:
            self._eip_pull_unlock()

    def _eip_pull_targeted(self, conditions):
        """Targeted pull (wizard): same loop, same daily counter, but it
        never touches the watermark or the breakpoint."""
        self.ensure_one()
        self = self.sudo()
        self._eip_pull_lock()
        try:
            return self._eip_pull_pages(
                self._eip_pull_state(), dict(conditions), 1, None,
                advance=False)
        finally:
            self._eip_pull_unlock()

    def _eip_pull_pages(self, state, conditions, page, window_end, advance):
        """Fetch every page of one frozen query.

        Each request is counted and logged *before* it leaves, and that
        is committed: a failed page or a crash can never erase calls that
        were really made, which is what keeps the daily limit exact.
        """
        self.ensure_one()
        transport = self.env['sn.wsd.eip.transport']
        interface = self.env['sn.wsd.eip.interface']._eip_interface(
            PULL_INTERFACE)
        page_size = min(self.pull_page_size or PULL_PAGE_SIZE_CAP,
                        PULL_PAGE_SIZE_CAP)
        limit = self.pull_daily_limit
        pages = 0
        rows = 0
        reason = 'done'
        detail = ''
        while True:
            # every value below is read again after each commit
            today = transport._eip_now().date()
            used = 0 if state.calls_date != today else state.calls_count
            if state.calls_date != today:
                state.write({'calls_date': today, 'calls_count': 0})
            if limit > 0 and used >= limit:
                reason = 'quota'
                detail = ('Daily limit reached: %s of %s requests used; '
                          'next page is %s.' % (used, limit, page))
                break
            body = dict(conditions)
            body.update({
                'purchaserHqCode': self.purchaser_hq_code,
                'supplierCode': self.supplier_code,
                'supplierName': self.supplier_name,
                'pageNum': page,
                'pageSize': page_size,
            })
            state.write({'calls_count': used + 1})
            log = transport._eip_open_log(
                self, interface, interface.operatetype_query, body, {
                    'page_num': page,
                    'filters': json.dumps(conditions, ensure_ascii=False),
                })
            self._eip_pull_commit()
            result = transport._eip_send(log, body)
            if not result['success']:
                reason = 'error'
                detail = result['error']
                break
            page_rows = result['data'] if isinstance(result['data'], list) else []
            self.env['sn.wsd.eip.purchase.order.line']._eip_pull_upsert(
                page_rows, self.company_id)
            log.write({
                'row_count': len(page_rows),
                'page_info': json.dumps(result['page_info']),
            })
            pages += 1
            rows += len(page_rows)
            page_count = result['page_info'].get('pageCount')
            # stop on an empty page, or on the last page the platform
            # announced; without a usable page count the empty page is
            # the only end marker, capped as a safety net
            if (not page_rows or (page_count and page >= page_count)
                    or page >= PULL_MAX_PAGES):
                break
            page += 1
            if advance:
                state.write({'pending_page': page})
            self._eip_pull_commit()
        values = {
            'last_run_at': fields.Datetime.now(),
            'last_run_pages': pages,
            'last_run_rows': rows,
            'last_run_reason': reason,
            'last_run_detail': detail or False,
        }
        if advance and reason == 'done':
            values.update({
                'watermark': window_end,
                'pending_start': False,
                'pending_end': False,
                'pending_page': 0,
            })
        state.write(values)
        return {
            'reason': reason,
            'pages': pages,
            'rows': rows,
            'detail': detail,
            'next_page': page if reason != 'done' else 0,
            'used': state.calls_count,
            'limit': limit,
        }


class EipPullState(models.Model):
    """Runtime state of the purchase-order pull of one integration
    config: watermark, unfinished window and breakpoint, today's call
    counter and the last run summary."""
    _name = 'sn.wsd.eip.pull.state'
    _description = 'EIP Purchase Order Pull State'
    _order = 'config_id'
    _check_company_auto = True

    config_id = fields.Many2one(
        'sn.wsd.eip.config', string='Integration Config', required=True,
        index=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(
        related='config_id.company_id', string='Company', store=True,
        readonly=True)
    watermark = fields.Datetime(
        string='Watermark',
        help='Start of the last fully pulled window; the next incremental '
             'pull asks for everything updated since this instant minus '
             'the overlap.')
    pending_start = fields.Datetime(
        string='Unfinished Window Start',
        help='Start of a window that is not fully pulled yet; empty means '
             'the window was opened without an update-time condition.')
    pending_end = fields.Datetime(
        string='Unfinished Window End',
        help='Set while a window is being pulled (also across several '
             'days); cleared once it is complete.')
    pending_page = fields.Integer(
        string='Next Page', default=0,
        help='Page the next run resumes from.')
    calls_date = fields.Date(
        string='Counted On', help='Beijing calendar day of the counter.')
    calls_count = fields.Integer(
        string="Today's Calls", default=0,
        help='Pull requests sent on the counted day, manual and scheduled '
             'alike.')
    last_run_at = fields.Datetime(string='Last Run')
    last_run_pages = fields.Integer(string='Last Run Pages')
    last_run_rows = fields.Integer(string='Last Run Rows')
    last_run_reason = fields.Selection(
        [('done', 'Completed'), ('quota', 'Daily Limit Reached'),
         ('error', 'Platform Error')],
        string='Last Run Result', readonly=True)
    last_run_detail = fields.Char(string='Last Run Detail', readonly=True)

    _config_uniq = models.Constraint(
        'unique(config_id)',
        'Only one pull state per integration config.',
    )

    pull_log_count = fields.Integer(
        string='Pull Logs', compute='_compute_pull_log_count')

    def _compute_pull_log_count(self):
        groups = self.env['sn.wsd.eip.pull.log'].sudo()._read_group(
            [('config_id', 'in', self.config_id.ids)],
            ['config_id'], ['__count'])
        counts = {config.id: count for config, count in groups}
        for state in self:
            state.pull_log_count = counts.get(state.config_id.id, 0)

    def action_view_pull_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pull Logs'),
            'res_model': 'sn.wsd.eip.pull.log',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }

    def action_pull_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pull Purchase Orders'),
            'res_model': 'sn.wsd.eip.pull.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_config_id': self.config_id.id},
        }


class EipPullWizard(models.TransientModel):
    """Manual pull: incremental (exactly what the scheduled job does) or
    targeted with optional query conditions."""
    _name = 'sn.wsd.eip.pull.wizard'
    _description = 'EIP Pull Purchase Orders Wizard'

    config_id = fields.Many2one(
        'sn.wsd.eip.config', string='Integration Config', required=True,
        default=lambda self: self.env.context.get('default_config_id')
        or self.env['sn.wsd.eip.config']._eip_config_for().id)
    mode = fields.Selection(
        [('incremental', 'Incremental'), ('targeted', 'Targeted')],
        string='Mode', required=True, default='incremental',
        help='Incremental runs the same pull as the scheduled job. '
             'Targeted pulls what the conditions below match and leaves '
             'the watermark untouched.')
    seller_con_code = fields.Char(string='Contract No. (Legal System)')
    con_code = fields.Char(string='Contract No.')
    po_no = fields.Char(string='Purchase Order No.')
    seller_sign_start_time = fields.Date(string='Contract Signed From')
    seller_sign_end_time = fields.Date(string='Contract Signed To')
    modify_start_time = fields.Datetime(string='Updated From')
    modify_end_time = fields.Datetime(string='Updated To')
    result_summary = fields.Text(string='Result', readonly=True)

    def _targeted_conditions(self):
        transport = self.env['sn.wsd.eip.transport']
        self.ensure_one()
        conditions = {}
        if self.seller_sign_start_time:
            conditions['sellerSignStartTime'] = transport._eip_format_date(
                self.seller_sign_start_time)
        if self.seller_sign_end_time:
            conditions['sellerSignEndTime'] = transport._eip_format_date(
                self.seller_sign_end_time)
        if self.seller_con_code:
            conditions['sellerConCode'] = self.seller_con_code
        if self.con_code:
            conditions['conCode'] = self.con_code
        if self.po_no:
            conditions['poNo'] = self.po_no
        if self.modify_start_time:
            conditions['modifyStartTime'] = transport._eip_format_datetime(
                self.modify_start_time)
        if self.modify_end_time:
            conditions['modifyEndTime'] = transport._eip_format_datetime(
                self.modify_end_time)
        return conditions

    def _summary(self, result):
        if result['reason'] == 'done':
            return _(
                'Pull completed: %(pages)s page(s), %(rows)s row(s).',
                pages=result['pages'], rows=result['rows'])
        if result['reason'] == 'quota':
            if result['pages']:
                return _(
                    'Daily pull limit reached (%(used)s/%(limit)s). The '
                    'pull resumes from page %(page)s.',
                    used=result['used'], limit=result['limit'],
                    page=result['next_page'])
            return _(
                "Today's pull quota is used up: %(used)s/%(limit)s.",
                used=result['used'], limit=result['limit'])
        return _('The EIP platform rejected the pull: %s', result['detail'])

    def action_pull(self):
        self.ensure_one()
        if self.mode == 'incremental':
            result = self.config_id._eip_pull_incremental()
        else:
            conditions = self._targeted_conditions()
            if not conditions:
                raise UserError(_(
                    'Fill at least one condition for a targeted pull, or '
                    'use the incremental mode.'))
            result = self.config_id._eip_pull_targeted(conditions)
        self.write({'result_summary': self._summary(result)})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pull Purchase Orders'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class EipPullWorker(models.AbstractModel):
    """Scheduled-job entry of the purchase-order pull."""
    _name = 'sn.wsd.eip.pull.worker'
    _description = 'EIP Purchase Order Pull Worker'

    @api.model
    def run_pull(self):
        """One incremental pull per active integration config."""
        configs = self.env['sn.wsd.eip.config'].sudo().search(
            [('active', '=', True)])
        for config in configs:
            try:
                config._eip_pull_incremental()
            except Exception:  # noqa: BLE001 - one config must not block the next
                _logger.exception(
                    'EIP purchase-order pull failed for config %s', config)
