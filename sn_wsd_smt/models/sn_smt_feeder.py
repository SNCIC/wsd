from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

FEEDER_CHANNEL_COUNT = {'single': 1, 'dual': 2, 'triple': 3}


class SnSmtFeeder(models.Model):
    _name = 'sn.smt.feeder'
    _description = 'SMT Feeder'
    _order = 'feeder_sn, id'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    feeder_sn = fields.Char(string='FEEDER_SN', required=True, index=True)
    feeder_spec = fields.Char(string='Feeder Spec')
    channel_type = fields.Selection(
        [
            ('single', 'Single Channel'),
            ('dual', 'Dual Channel'),
            ('triple', 'Triple Channel'),
        ],
        string='Channel Type',
        required=True,
        default='single',
    )
    channel_ids = fields.One2many(
        'sn.smt.feeder.channel',
        'feeder_id',
        string='Channel SN',
    )
    channel_sn_summary = fields.Char(compute='_compute_channel_sn_summary')
    production_date = fields.Date(string='Production Date')
    usage_count = fields.Integer(string='Usage Count', default=0)
    usage_count_limit = fields.Integer(string='Usage Count Limit')
    maintenance_count = fields.Integer(string='Maintenance Count')
    remind_count = fields.Integer(string='Remind Count')
    usage_days_limit = fields.Integer(string='Usage Days Limit')
    maintenance_days = fields.Integer(string='Maintenance Days')
    remind_days = fields.Integer(string='Remind Days')
    last_maintenance_date = fields.Date(
        string='Last Maintenance Date',
        default=fields.Date.context_today,
    )
    status = fields.Selection(
        [
            ('normal', 'Normal'),
            ('in_use', 'In Use'),
            ('in_repair', 'In Repair'),
            ('disabled', 'Disabled'),
            ('scrapped', 'Scrapped'),
        ],
        string='Status',
        default='normal',
        required=True,
        index=True,
    )
    care_state = fields.Selection(
        [
            ('ok', 'OK'),
            ('remind', 'Remind'),
            ('maintain_due', 'Maintenance Due'),
            ('usage_expired', 'Usage Expired'),
        ],
        string='Care State',
        compute='_compute_care_state',
        store=True,
        index=True,
    )
    maintenance_ok = fields.Boolean(compute='_compute_maintenance_ok')
    bound_production_id = fields.Many2one(
        'mrp.production',
        string='Bound Manufacturing Order',
        check_company=True,
    )
    cart_id = fields.Many2one(
        'sn.smt.cart',
        string='Feeder Cart',
        copy=False,
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_smt_feeder_sn_unique = models.Constraint(
        'unique(company_id, feeder_sn)',
        'The feeder SN must be unique per company.',
    )

    @api.depends('feeder_sn')
    def _compute_name(self):
        for feeder in self:
            feeder.name = feeder.feeder_sn

    def _compute_channel_sn_summary(self):
        for feeder in self:
            feeder.channel_sn_summary = ' / '.join(
                feeder.channel_ids.mapped('channel_sn')
            )

    def _get_care_state(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.usage_count_limit and self.usage_count >= self.usage_count_limit:
            return 'usage_expired'
        if self.maintenance_count and self.usage_count >= self.maintenance_count:
            return 'maintain_due'
        if self.remind_count and self.usage_count >= self.remind_count:
            return 'remind'
        days = (today - self.last_maintenance_date).days if self.last_maintenance_date else 0
        if self.usage_days_limit and days >= self.usage_days_limit:
            return 'usage_expired'
        if self.maintenance_days and days >= self.maintenance_days:
            return 'maintain_due'
        if self.remind_days and days >= self.remind_days:
            return 'remind'
        return 'ok'

    @api.depends(
        'usage_count',
        'usage_count_limit',
        'maintenance_count',
        'remind_count',
        'usage_days_limit',
        'maintenance_days',
        'remind_days',
        'last_maintenance_date',
    )
    def _compute_care_state(self):
        for feeder in self:
            feeder.care_state = feeder._get_care_state()

    @api.depends(
        'status',
        'usage_count',
        'usage_count_limit',
        'maintenance_count',
        'remind_count',
        'usage_days_limit',
        'maintenance_days',
        'remind_days',
        'last_maintenance_date',
    )
    def _compute_maintenance_ok(self):
        for feeder in self:
            feeder.maintenance_ok = (
                feeder.status != 'scrapped'
                and feeder._get_care_state() not in ('maintain_due', 'usage_expired')
            )

    @api.constrains('channel_type', 'channel_ids')
    def _check_channel_count(self):
        for feeder in self:
            expected = FEEDER_CHANNEL_COUNT[feeder.channel_type]
            if len(feeder.channel_ids) != expected:
                raise ValidationError(_(
                    'The feeder "%(sn)s" must have exactly %(expected)s channel SN line(s) for its channel type.',
                    sn=feeder.feeder_sn,
                    expected=expected,
                ))

    def _ensure_not_bound(self):
        for feeder in self:
            if feeder.bound_production_id:
                raise UserError(_(
                    'The feeder "%(sn)s" is bound to manufacturing order %(order)s. Unload it first.',
                    sn=feeder.feeder_sn,
                    order=feeder.bound_production_id.display_name,
                ))
            if feeder.cart_id:
                raise UserError(_(
                    'The feeder "%(sn)s" is still on cart %(cart)s. Unbind it from the cart first.',
                    sn=feeder.feeder_sn,
                    cart=feeder.cart_id.cart_sn,
                ))

    def action_disable(self):
        for feeder in self:
            if feeder.status != 'normal':
                raise UserError(_('Only a normal feeder can be disabled.'))
            feeder._ensure_not_bound()
        self.write({'status': 'disabled'})

    def action_enable(self):
        for feeder in self:
            if feeder.status != 'disabled':
                raise UserError(_('Only a disabled feeder can be enabled.'))
        self.write({'status': 'normal'})

    def action_report_repair(self, fault_desc):
        for feeder in self:
            if feeder.status != 'normal':
                raise UserError(_('Only a normal feeder can be reported for repair.'))
            feeder._ensure_not_bound()
            self.env['sn.smt.feeder.repair'].create({
                'feeder_id': feeder.id,
                'fault_desc': fault_desc,
            })
        self.write({'status': 'in_repair'})

    def action_complete_repair(self, result):
        for feeder in self:
            if feeder.status != 'in_repair':
                raise UserError(_('Only a feeder in repair can be completed.'))
        self.write({'status': 'normal'})
        open_repairs = self.env['sn.smt.feeder.repair'].search([
            ('feeder_id', 'in', self.ids),
            ('done_at', '=', False),
        ])
        open_repairs.write({'done_at': fields.Datetime.now(), 'result': result})

    def action_scrap(self, reason, trigger='manual'):
        for feeder in self:
            if feeder.status == 'scrapped':
                raise UserError(_('The feeder is already scrapped.'))
            feeder._ensure_not_bound()
            self.env['sn.smt.feeder.scrap'].create({
                'feeder_id': feeder.id,
                'reason': reason,
                'trigger': trigger,
            })
        self.write({'status': 'scrapped'})

    def action_maintenance(self):
        maintenance = self.env['sn.smt.feeder.maintenance']
        for feeder in self:
            if feeder.status == 'scrapped':
                raise UserError(_('A scrapped feeder cannot be maintained.'))
            if feeder.care_state == 'usage_expired':
                raise UserError(_(
                    'The feeder reached its usage limit and must be scrapped, not maintained.'))
            today = fields.Date.context_today(feeder)
            if feeder.maintenance_count and feeder.usage_count >= feeder.maintenance_count:
                trigger = 'count_due'
            elif feeder.last_maintenance_date and feeder.maintenance_days \
                    and (today - feeder.last_maintenance_date).days >= feeder.maintenance_days:
                trigger = 'period_due'
            else:
                trigger = 'manual'
            maintenance.create({
                'feeder_id': feeder.id,
                'trigger': trigger,
                'snapshot_usage_count': feeder.usage_count,
            })
            feeder.write({
                'usage_count': 0,
                'last_maintenance_date': today,
            })
        return True

    def _open_action_wizard(self, action):
        self.ensure_one()
        action_name = self.env.ref('sn_wsd_smt.action_sn_smt_feeder_action_wizard').name
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.smt.feeder.action.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': action_name,
            'context': {'default_feeder_id': self.id, 'default_action': action},
        }

    def action_open_report_repair(self):
        return self._open_action_wizard('report_repair')

    def action_open_complete_repair(self):
        return self._open_action_wizard('complete_repair')

    def action_open_scrap(self):
        return self._open_action_wizard('scrap')

    def _auto_scrap_expired(self):
        expired = self.filtered(
            lambda f: f.care_state == 'usage_expired' and f.status != 'scrapped'
        )
        if expired:
            expired.action_scrap(
                _('Usage count or usage period limit reached.'),
                trigger='usage_limit',
            )

    @api.model
    def add_usage(self, items):
        """Batch usage accumulation: items = [{'sn': str, 'qty': int}, ...].

        `sn` may be a feeder SN or a channel SN; the usage count is always
        accumulated on the whole feeder. All updates happen in the current
        transaction.
        """
        if not items:
            return self
        feeder_model = self.env['sn.smt.feeder']
        channel_model = self.env['sn.smt.feeder.channel']
        resolved = {}
        for item in items:
            sn, qty = item.get('sn'), item.get('qty', 1)
            if not sn or qty <= 0:
                raise UserError(_('Invalid usage item: %(item)s', item=str(item)))
            feeder = feeder_model.search(
                [('feeder_sn', '=', sn), ('company_id', 'in', self.env.companies.ids)],
                limit=2,
            )
            if len(feeder) > 1:
                raise UserError(_('The feeder SN "%s" is ambiguous.') % sn)
            if not feeder:
                channels = channel_model.search(
                    [('channel_sn', '=', sn), ('company_id', 'in', self.env.companies.ids)],
                    limit=2,
                )
                if len(channels) > 1:
                    raise UserError(_('The channel SN "%s" is ambiguous.') % sn)
                if not channels:
                    raise UserError(_('No feeder found for SN "%s".') % sn)
                feeder = channels.feeder_id
            if feeder.status == 'scrapped':
                raise UserError(_('The feeder SN "%s" is scrapped.') % feeder.feeder_sn)
            resolved[feeder.id] = resolved.get(feeder.id, 0) + qty
        feeders = self.browse(resolved.keys())
        for feeder in feeders:
            feeder.usage_count += resolved[feeder.id]
        feeders._auto_scrap_expired()
        return feeders

    @api.model
    def cron_refresh_care_state(self):
        feeders = self.search([])
        self.env.add_to_compute(self._fields['care_state'], feeders)
        self.env.flush_all()
        feeders._auto_scrap_expired()
        return True


class SnSmtFeederChannel(models.Model):
    _name = 'sn.smt.feeder.channel'
    _description = 'SMT Feeder Channel'
    _order = 'feeder_id, channel_no, id'

    feeder_id = fields.Many2one(
        'sn.smt.feeder',
        string='FEEDER_SN',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    channel_no = fields.Integer(string='Channel No', required=True)
    channel_sn = fields.Char(string='Channel SN', required=True, index=True)
    company_id = fields.Many2one(
        related='feeder_id.company_id',
        store=True,
        index=True,
    )

    _sn_smt_channel_sn_unique = models.Constraint(
        'unique(company_id, channel_sn)',
        'The channel SN must be unique per company.',
    )

    @api.constrains('channel_no')
    def _check_channel_no(self):
        for channel in self:
            if channel.channel_no not in (1, 2, 3):
                raise ValidationError(_('The channel number must be 1, 2 or 3.'))


class SnSmtFeederRepair(models.Model):
    _name = 'sn.smt.feeder.repair'
    _description = 'SMT Feeder Repair Record'
    _order = 'reported_at desc, id desc'

    feeder_id = fields.Many2one(
        'sn.smt.feeder',
        string='FEEDER_SN',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    fault_desc = fields.Text(string='Fault Description', required=True)
    reported_by = fields.Many2one(
        'res.users',
        string='Reported By',
        default=lambda self: self.env.user,
        required=True,
    )
    reported_at = fields.Datetime(
        string='Reported At',
        default=fields.Datetime.now,
        required=True,
    )
    done_at = fields.Datetime(string='Completed At')
    result = fields.Text(string='Repair Result')
    company_id = fields.Many2one(
        related='feeder_id.company_id',
        store=True,
        index=True,
    )


class SnSmtFeederScrap(models.Model):
    _name = 'sn.smt.feeder.scrap'
    _description = 'SMT Feeder Scrap Record'
    _order = 'scrapped_at desc, id desc'

    feeder_id = fields.Many2one(
        'sn.smt.feeder',
        string='FEEDER_SN',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    reason = fields.Text(string='Reason')
    trigger = fields.Selection(
        [('manual', 'Manual'), ('usage_limit', 'Usage Limit')],
        string='Trigger',
        default='manual',
        required=True,
    )
    scrapped_by = fields.Many2one(
        'res.users',
        string='Scrapped By',
        default=lambda self: self.env.user,
        required=True,
    )
    scrapped_at = fields.Datetime(
        string='Scrapped At',
        default=fields.Datetime.now,
        required=True,
    )
    company_id = fields.Many2one(
        related='feeder_id.company_id',
        store=True,
        index=True,
    )


class SnSmtFeederMaintenance(models.Model):
    _name = 'sn.smt.feeder.maintenance'
    _description = 'SMT Feeder Maintenance Record'
    _order = 'maintained_at desc, id desc'

    feeder_id = fields.Many2one(
        'sn.smt.feeder',
        string='FEEDER_SN',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    trigger = fields.Selection(
        [
            ('count_due', 'Count Due'),
            ('period_due', 'Period Due'),
            ('manual', 'Manual'),
        ],
        string='Trigger',
        default='manual',
        required=True,
    )
    maintained_by = fields.Many2one(
        'res.users',
        string='Maintained By',
        default=lambda self: self.env.user,
        required=True,
    )
    maintained_at = fields.Datetime(
        string='Maintained At',
        default=fields.Datetime.now,
        required=True,
    )
    snapshot_usage_count = fields.Integer(string='Snapshot Usage Count')
    company_id = fields.Many2one(
        related='feeder_id.company_id',
        store=True,
        index=True,
    )
