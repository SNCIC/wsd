from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

AUX_STATE_SELECTION = [
    ('normal', 'In Stock'),
    ('issued', 'Issued'),
    ('thawing', 'Thawing'),
    ('ready', 'Ready'),
    ('in_use', 'In Use'),
    ('disabled', 'Disabled'),
    ('exhausted', 'Exhausted'),
    ('scrapped', 'Scrapped'),
]

RECORD_ACTION_SELECTION = [
    ('issue', 'Issue'),
    ('return', 'Return'),
    ('thaw_start', 'Thaw Start'),
    ('thaw_end', 'Thaw End'),
    ('stir_start', 'Stir Start'),
    ('stir_end', 'Stir End'),
    ('load', 'Load'),
    ('unload', 'Unload'),
    ('exhaust', 'Exhaust'),
    ('scrap', 'Scrap'),
    ('disable', 'Disable'),
    ('enable', 'Enable'),
    ('usage', 'Usage'),
]

EXPIRY_STATE_SELECTION = [
    ('ok', 'Valid'),
    ('remind', 'Expiring Soon'),
    ('expired', 'Expired'),
]

TERMINAL_STATES = ('exhausted', 'scrapped')


class SnConsumableType(models.Model):
    _name = 'sn.consumable.type'
    _description = 'Consumable Type'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Type Name', required=True)
    active = fields.Boolean(default=True)
    thaw_duration_min = fields.Integer(string='Thaw Duration Min (min)', default=0)
    thaw_duration_max = fields.Integer(string='Thaw Duration Max (min)', default=0)
    thaw_count_limit = fields.Integer(
        string='Thaw Count Limit',
        help='When exceeded the consumable must be scrapped.')
    stir_control = fields.Boolean(string='Stir Control')
    stir_duration_min = fields.Integer(string='Stir Duration Min (min)', default=0)
    stir_duration_max = fields.Integer(string='Stir Duration Max (min)', default=0)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_consumable_type_name_unique = models.Constraint(
        'unique(company_id, name)',
        'The consumable type name must be unique per company.',
    )

    @api.constrains('thaw_duration_min', 'thaw_duration_max')
    def _check_thaw_duration(self):
        for consumable_type in self:
            if consumable_type.thaw_duration_min and consumable_type.thaw_duration_max \
                    and consumable_type.thaw_duration_min > consumable_type.thaw_duration_max:
                raise ValidationError(_('Thaw duration min cannot be greater than thaw duration max.'))

    @api.constrains('stir_duration_min', 'stir_duration_max')
    def _check_stir_duration(self):
        for consumable_type in self:
            if consumable_type.stir_duration_min and consumable_type.stir_duration_max \
                    and consumable_type.stir_duration_min > consumable_type.stir_duration_max:
                raise ValidationError(_('Stir duration min cannot be greater than stir duration max.'))


class SnConsumableTemplate(models.Model):
    _name = 'sn.consumable.template'
    _description = 'Consumable Template'
    _inherit = ['mail.thread']
    _order = 'code, id'
    _check_company_auto = True

    code = fields.Char(string='Consumable Code', required=True, index=True, tracking=True)
    name = fields.Char(string='Consumable Name', required=True, tracking=True)
    spec = fields.Char(string='Consumable Spec')
    type_id = fields.Many2one(
        'sn.consumable.type',
        string='Consumable Type',
        required=True,
        index=True,
        ondelete='restrict',
        check_company=True,
        tracking=True,
    )
    thaw_duration_min = fields.Integer(string='Thaw Duration Min (min)', default=0)
    thaw_duration_max = fields.Integer(string='Thaw Duration Max (min)', default=0)
    thaw_count_limit = fields.Integer(
        string='Thaw Count Limit',
        help='When exceeded the consumable must be scrapped.')
    stir_control = fields.Boolean(string='Stir Control')
    stir_duration_min = fields.Integer(string='Stir Duration Min (min)', default=0)
    stir_duration_max = fields.Integer(string='Stir Duration Max (min)', default=0)
    shelf_life_days = fields.Integer(string='Shelf Life (days)', required=True)
    expiry_remind_days = fields.Integer(string='Expiry Remind (days)', required=True)
    active = fields.Boolean(default=True)
    info_ids = fields.One2many('sn.consumable.info', 'template_id', string='Consumable Info')
    info_count = fields.Integer(compute='_compute_info_count')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_consumable_code_unique = models.Constraint(
        'unique(company_id, code)',
        'The consumable code must be unique per company.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for template in self:
            template.display_name = ' - '.join(
                part for part in (template.code, template.name) if part)

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        if name:
            domain = list(domain or []) + [
                '|', ('code', operator, name), ('name', operator, name)]
            return super().name_search('', domain=domain, operator='ilike', limit=limit)
        return super().name_search(name, domain=domain, operator=operator, limit=limit)

    @api.depends('info_ids')
    def _compute_info_count(self):
        for template in self:
            template.info_count = len(template.info_ids)

    @api.onchange('type_id')
    def _onchange_type_id(self):
        # Prefill copies the type defaults only onto untouched fields, so
        # re-selecting a type never overwrites values the user already set.
        consumable_type = self.type_id
        if not consumable_type:
            return
        if not self.thaw_duration_min and not self.thaw_duration_max:
            self.thaw_duration_min = consumable_type.thaw_duration_min
            self.thaw_duration_max = consumable_type.thaw_duration_max
        if not self.thaw_count_limit:
            self.thaw_count_limit = consumable_type.thaw_count_limit
        if not self.stir_control:
            self.stir_control = consumable_type.stir_control
            if not self.stir_duration_min and not self.stir_duration_max:
                self.stir_duration_min = consumable_type.stir_duration_min
                self.stir_duration_max = consumable_type.stir_duration_max

    @api.constrains('thaw_duration_min', 'thaw_duration_max')
    def _check_thaw_duration(self):
        for template in self:
            if template.thaw_duration_min and template.thaw_duration_max \
                    and template.thaw_duration_min > template.thaw_duration_max:
                raise ValidationError(_('Thaw duration min cannot be greater than thaw duration max.'))

    @api.constrains('stir_duration_min', 'stir_duration_max')
    def _check_stir_duration(self):
        for template in self:
            if template.stir_duration_min and template.stir_duration_max \
                    and template.stir_duration_min > template.stir_duration_max:
                raise ValidationError(_('Stir duration min cannot be greater than stir duration max.'))


class SnConsumableInfo(models.Model):
    _name = 'sn.consumable.info'
    _description = 'Consumable Info'
    _order = 'sn, id'
    _rec_name = 'sn'
    _check_company_auto = True

    sn = fields.Char(string='Consumable SN', required=True, index=True)
    template_id = fields.Many2one(
        'sn.consumable.template',
        string='Consumable Code',
        required=True,
        ondelete='restrict',
        index=True,
        check_company=True,
    )
    template_code = fields.Char(related='template_id.code', store=True, index=True)
    type_id = fields.Many2one(related='template_id.type_id', store=True, index=True)
    stir_control = fields.Boolean(related='template_id.stir_control')
    aux_state = fields.Selection(
        AUX_STATE_SELECTION, string='Status', default='normal', required=True, index=True)
    production_date = fields.Date(string='Production Date')
    expiry_date = fields.Date(
        string='Expiry Date', compute='_compute_expiry_date', store=True, index=True)
    expiry_state = fields.Selection(
        EXPIRY_STATE_SELECTION, string='Expiry State', compute='_compute_expiry_state')
    supplier_id = fields.Many2one('res.partner', string='Supplier', check_company=True)
    purchase_ref = fields.Char(string='Purchase Order')
    weight_g = fields.Float(string='Weight (g)')
    location_id = fields.Many2one('stock.location', string='Location', check_company=True)
    thaw_count = fields.Integer(string='Thaw Count', default=0, copy=False)
    issued_user_id = fields.Many2one('res.users', string='Issued By')
    issued_date = fields.Datetime(string='Issued Date')
    thaw_start = fields.Datetime(string='Last Thaw Start', copy=False, readonly=True)
    thaw_end = fields.Datetime(string='Last Thaw End', copy=False, readonly=True)
    thaw_minutes = fields.Float(string='Thaw Minutes (last)', copy=False, readonly=True)
    stir_start = fields.Datetime(string='Last Stir Start', copy=False, readonly=True)
    stir_end = fields.Datetime(string='Last Stir End', copy=False, readonly=True)
    stir_minutes = fields.Float(string='Stir Minutes (last)', copy=False, readonly=True)
    record_ids = fields.One2many('sn.consumable.record', 'info_id', string='History')
    total_usage_count = fields.Integer(
        string='Total Usage Count', copy=False,
        help='Accumulated station-pass usage (key-material controlled).')
    record_count = fields.Integer(compute='_compute_record_count')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_consumable_sn_unique = models.Constraint(
        'unique(company_id, sn)',
        'The consumable SN must be unique per company.',
    )

    @api.depends('production_date', 'template_id.shelf_life_days')
    def _compute_expiry_date(self):
        for info in self:
            if info.production_date and info.template_id.shelf_life_days:
                info.expiry_date = fields.Date.add(
                    info.production_date, days=info.template_id.shelf_life_days)
            else:
                info.expiry_date = False

    @api.depends('expiry_date', 'template_id.expiry_remind_days', 'aux_state')
    def _compute_expiry_state(self):
        today = fields.Date.context_today(self)
        for info in self:
            if info.aux_state in TERMINAL_STATES:
                # An exhausted/scrapped consumable has no meaningful expiry.
                info.expiry_state = False
            elif not info.expiry_date:
                info.expiry_state = 'ok'
            elif info.expiry_date < today:
                info.expiry_state = 'expired'
            elif info.expiry_date <= fields.Date.add(
                    today, days=info.template_id.expiry_remind_days or 0):
                info.expiry_state = 'remind'
            else:
                info.expiry_state = 'ok'

    @api.depends('record_ids')
    def _compute_record_count(self):
        for info in self:
            info.record_count = len(info.record_ids)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _ensure_not_terminal(self):
        for info in self:
            if info.aux_state in TERMINAL_STATES:
                raise UserError(_('The consumable %s is already in a terminal state.', info.sn))

    def _ensure_not_expired(self):
        today = fields.Date.context_today(self)
        for info in self:
            if info.expiry_date and info.expiry_date < today:
                raise UserError(_(
                    'The consumable %s expired on %s. Scrap it.',
                    info.sn, fields.Date.to_string(info.expiry_date)))

    def _ensure_stir_done(self):
        for info in self:
            # Datetime columns only carry second precision, so a stir started
            # in the same second the thaw ended still counts as "after".
            if info.stir_control and (not info.stir_start or not info.stir_end
                                      or not info.thaw_end
                                      or info.stir_start < info.thaw_end):
                raise UserError(_(
                    'The consumable %s must be stirred after the current thaw before loading.',
                    info.sn))

    def register_usage(self, qty, mes_order=False):
        """Station-pass usage counting (key-material controlled only):
        mirrors sn.tooling.register_usage."""
        for info in self:
            # 状态字段是 aux_state，上线后的在用态是 in_use（与制具的
            # online 对应）；原实现误用不存在的 state 字段与 loaded 键
            if info.aux_state != 'in_use':
                raise UserError(_(
                    'Only an in-use consumable can register usage (%s).', info.sn))
            if not isinstance(qty, int) or qty <= 0:
                raise UserError(_('The usage quantity must be a positive integer.'))
            info.total_usage_count = info.total_usage_count + qty
            info._record('usage', mes_order=mes_order)
        return True

    def _record(self, action, mes_order=False, duration=False, reason=False):
        return self.env['sn.consumable.record'].create({
            'info_id': self.id,
            'action': action,
            'mes_order_id': mes_order.id if mes_order else False,
            'duration_minutes': duration,
            'thaw_count': self.thaw_count,
            'scrap_reason': reason,
        })

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def action_issue(self):
        for info in self:
            if info.aux_state != 'normal':
                raise UserError(_('Only an in-stock consumable can be issued.'))
            info._ensure_not_expired()
            info.write({
                'aux_state': 'issued',
                'issued_user_id': self.env.user.id,
                'issued_date': fields.Datetime.now(),
            })
            info._record('issue')
        return True

    def action_return(self):
        for info in self:
            if info.aux_state != 'issued':
                raise UserError(_('Only an issued consumable can be returned.'))
            info.write({
                'aux_state': 'normal',
                'issued_user_id': False,
                'issued_date': False,
            })
            info._record('return')
        return True

    def action_thaw_start(self):
        for info in self:
            if info.aux_state != 'issued':
                raise UserError(_('Only an issued consumable can start thawing.'))
            info._ensure_not_expired()
            limit = info.template_id.thaw_count_limit
            if limit and info.thaw_count + 1 > limit:
                raise UserError(_(
                    'The consumable %s reached the thaw count limit (%s). Scrap it.',
                    info.sn, limit))
            info.write({
                'thaw_count': info.thaw_count + 1,
                'thaw_start': fields.Datetime.now(),
                'thaw_end': False,
                'aux_state': 'thawing',
            })
            info._record('thaw_start')
        return True

    def action_thaw_end(self):
        for info in self:
            if info.aux_state != 'thawing':
                raise UserError(_('The consumable %s is not thawing.', info.sn))
            minutes = info._minutes_since(info.thaw_start)
            template = info.template_id
            if template.thaw_duration_min and minutes < template.thaw_duration_min:
                raise UserError(_(
                    'The thaw duration of %s is only %s min, at least %s min is required. Keep waiting.',
                    info.sn, round(minutes), template.thaw_duration_min))
            if template.thaw_duration_max and minutes > template.thaw_duration_max:
                raise UserError(_(
                    'The thaw duration of %s is %s min and exceeded the limit of %s min. Scrap it.',
                    info.sn, round(minutes), template.thaw_duration_max))
            info.write({
                'thaw_end': fields.Datetime.now(),
                'thaw_minutes': minutes,
                'aux_state': 'ready',
            })
            info._record('thaw_end', duration=minutes)
        return True

    def action_stir_start(self):
        for info in self:
            if not info.template_id.stir_control:
                raise UserError(_('Stir control is not enabled for %s.', info.template_id.code))
            if info.aux_state != 'ready':
                raise UserError(_('The consumable %s must finish thawing before stirring.', info.sn))
            info.write({'stir_start': fields.Datetime.now(), 'stir_end': False})
            info._record('stir_start')
        return True

    def action_stir_end(self):
        for info in self:
            if not info.stir_start:
                raise UserError(_('The consumable %s is not stirring.', info.sn))
            minutes = info._minutes_since(info.stir_start)
            template = info.template_id
            if template.stir_duration_min and minutes < template.stir_duration_min:
                raise UserError(_(
                    'The stir duration of %s is only %s min, at least %s min is required. Keep stirring.',
                    info.sn, round(minutes), template.stir_duration_min))
            if template.stir_duration_max and minutes > template.stir_duration_max:
                raise UserError(_(
                    'The stir duration of %s is %s min and exceeded the limit of %s min. Scrap it.',
                    info.sn, round(minutes), template.stir_duration_max))
            info.write({
                'stir_end': fields.Datetime.now(),
                'stir_minutes': minutes,
            })
            info._record('stir_end', duration=minutes)
        return True

    def action_load(self, mes_order):
        for info in self:
            if info.aux_state != 'ready':
                raise UserError(_('The consumable %s is not ready to load.', info.sn))
            info._ensure_not_expired()
            info._ensure_stir_done()
            info.write({'aux_state': 'in_use'})
            info._record('load', mes_order=mes_order)
        return True

    def action_unload(self):
        Record = self.env['sn.consumable.record']
        for info in self:
            if info.aux_state != 'in_use':
                raise UserError(_('The consumable %s is not in use.', info.sn))
            last_load = Record.search(
                [('info_id', '=', info.id), ('action', '=', 'load')], order='id desc', limit=1)
            info.write({'aux_state': 'issued'})
            info._record('unload', mes_order=last_load.mes_order_id)
        return True

    def action_exhaust(self):
        for info in self:
            info._ensure_not_terminal()
            info.write({'aux_state': 'exhausted'})
            info._record('exhaust')
        return True

    def action_scrap(self, reason=False):
        for info in self:
            info._ensure_not_terminal()
            info.write({'aux_state': 'scrapped'})
            info._record('scrap', reason=reason)
        return True

    def action_disable(self):
        for info in self:
            info._ensure_not_terminal()
            info.write({'aux_state': 'disabled'})
            info._record('disable')
        return True

    def action_enable(self):
        for info in self:
            if info.aux_state != 'disabled':
                raise UserError(_('Only a disabled consumable can be enabled.'))
            info.write({'aux_state': 'normal'})
            info._record('enable')
        return True

    # ------------------------------------------------------------------
    # Wizards
    # ------------------------------------------------------------------

    def action_open_load(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.consumable.load.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': self.env.ref('sn_wsd_consumable.action_sn_consumable_load_wizard').name,
            'context': {'default_info_id': self.id},
        }

    def action_open_scrap(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.consumable.scrap.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': self.env.ref('sn_wsd_consumable.action_sn_consumable_scrap_wizard').name,
            'context': {'default_info_id': self.id},
        }

    def _minutes_since(self, start):
        if not start:
            return 0.0
        return round((fields.Datetime.now() - start).total_seconds() / 60.0, 2)


class SnConsumableRecord(models.Model):
    _name = 'sn.consumable.record'
    _description = 'Consumable Record'
    _order = 'info_id, id desc'
    _check_company_auto = True

    info_id = fields.Many2one(
        'sn.consumable.info',
        string='Consumable SN',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    template_id = fields.Many2one(
        'sn.consumable.template',
        related='info_id.template_id',
        store=True,
        index=True,
    )
    action = fields.Selection(RECORD_ACTION_SELECTION, string='Action', required=True, index=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', index=True, check_company=True)
    duration_minutes = fields.Float(string='Duration (min)')
    thaw_count = fields.Integer(string='Thaw Count')
    scrap_reason = fields.Char(string='Scrap Reason')
    user_id = fields.Many2one(
        'res.users', string='User', default=lambda self: self.env.user, required=True)
    occurred_at = fields.Datetime(string='Occurred At', default=fields.Datetime.now, required=True)
    company_id = fields.Many2one(
        'res.company', related='info_id.company_id', store=True, index=True)
