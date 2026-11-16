from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PARAM_CATEGORIES = [
    ('barrel', '料筒温度'),
    ('mold', '模具温度'),
    ('inject', '注射'),
    ('hold', '保压'),
    ('meter', '计量/塑化'),
    ('time', '时间/周期'),
    ('weight', '重量'),
]

# (类别, 代码, 名称, 单位, 是否逐模监控)
PARAM_TEMPLATE = [
    ('barrel', 'barrel_t1', '料筒温度 1 段（喷嘴）', '℃', False),
    ('barrel', 'barrel_t2', '料筒温度 2 段', '℃', False),
    ('barrel', 'barrel_t3', '料筒温度 3 段', '℃', False),
    ('barrel', 'barrel_t4', '料筒温度 4 段', '℃', False),
    ('barrel', 'barrel_t5', '料筒温度 5 段（下料口）', '℃', False),
    ('barrel', 'melt_t', '熔体温度（料温）', '℃', True),
    ('mold', 'mold_t_fixed', '模温（定模）', '℃', True),
    ('mold', 'mold_t_moving', '模温（动模）', '℃', False),
    ('inject', 'inj_p1', '射出压力 1 段', 'MPa', False),
    ('inject', 'inj_p2', '射出压力 2 段', 'MPa', False),
    ('inject', 'inj_p3', '射出压力 3 段', 'MPa', False),
    ('inject', 'inj_v1', '射出速度 1 段', 'mm/s', False),
    ('inject', 'inj_v2', '射出速度 2 段', 'mm/s', False),
    ('inject', 'inj_v3', '射出速度 3 段', 'mm/s', False),
    ('inject', 'vp_pos', 'V/P 切换位置', 'mm', True),
    ('inject', 'peak_p', '射出峰值压力', 'MPa', True),
    ('inject', 'inj_time', '注射时间', 's', True),
    ('hold', 'hold_p1', '保压压力 1 段', 'MPa', True),
    ('hold', 'hold_p2', '保压压力 2 段', 'MPa', False),
    ('hold', 'hold_t1', '保压时间 1 段', 's', False),
    ('hold', 'hold_t2', '保压时间 2 段', 's', False),
    ('meter', 'meter_pos', '计量位置', 'mm', False),
    ('meter', 'back_p', '背压', 'MPa', False),
    ('meter', 'screw_rpm', '螺杆转速', 'rpm', False),
    ('meter', 'meter_time', '计量时间', 's', True),
    ('meter', 'cushion', '垫料量（余料）', 'mm', True),
    ('time', 'cool_time', '冷却时间', 's', False),
    ('time', 'cycle', '成型周期', 's', True),
    ('weight', 'part_w', '单件重', 'g', False),
    ('weight', 'runner_w', '水口重', 'g', False),
]
PARAM_UNITS = {code: unit for _c, code, _n, unit, _m in PARAM_TEMPLATE}
PARAM_NAMES = {code: name for _c, code, name, _u, _m in PARAM_TEMPLATE}


class SnInjProcessCard(models.Model):
    """标准成型工艺卡：产品 + 模具 + 机台/吨位段，参数逐项「标准值 + 上下限」；
    版本化（草稿 → 审核中 → 生效 → 作废），同一产品+模具同时只能有一个生效版本。"""
    _name = 'sn.inj.process.card'
    _description = '注塑标准工艺卡'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'product_id, mold_id, version desc'

    name = fields.Char(string='工艺卡号', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    product_id = fields.Many2one('product.product', string='产品', required=True, tracking=True)
    mold_id = fields.Many2one('sn.inj.mold', string='模具', required=True, tracking=True)
    machine_id = fields.Many2one('sn.inj.machine', string='指定机台')
    tonnage_min = fields.Integer(string='适用吨位下限(T)')
    tonnage_max = fields.Integer(string='适用吨位上限(T)')
    grade_id = fields.Many2one('sn.inj.material.grade', string='料种')
    color_recipe_id = fields.Many2one('sn.inj.color.recipe', string='配色配方')
    version = fields.Integer(string='版本号', default=1, copy=False)
    version_label = fields.Char(string='版本', compute='_compute_version_label', store=True)
    state = fields.Selection(
        [('draft', '草稿'), ('review', '审核中'), ('active', '生效'), ('obsolete', '作废')],
        string='状态', default='draft', required=True, tracking=True, copy=False)
    cavity = fields.Integer(string='有效穴数', compute='_compute_cavity')
    std_cycle = fields.Float(string='标准周期(s)', tracking=True)
    cool_time = fields.Float(string='冷却时间(s)')
    part_weight = fields.Float(string='单件重(g)')
    runner_weight = fields.Float(string='水口重(g)')
    shot_weight = fields.Float(string='单模射胶量(g)', compute='_compute_shot_weight')
    regrind_max_pct = fields.Float(string='水口料上限(%)')
    line_ids = fields.One2many('sn.inj.process.card.line', 'card_id', string='全部参数', copy=True)
    barrel_line_ids = fields.One2many('sn.inj.process.card.line', 'card_id', string='料筒/模温',
                                      domain=[('category', 'in', ('barrel', 'mold'))])
    inject_line_ids = fields.One2many('sn.inj.process.card.line', 'card_id', string='注射/保压',
                                      domain=[('category', 'in', ('inject', 'hold'))])
    meter_line_ids = fields.One2many('sn.inj.process.card.line', 'card_id', string='计量/时间/重量',
                                     domain=[('category', 'in', ('meter', 'time', 'weight'))])
    change_note = fields.Text(string='变更说明')
    submit_user_id = fields.Many2one('res.users', string='提交人', copy=False)
    submit_date = fields.Datetime(string='提交时间', copy=False)
    approve_user_id = fields.Many2one('res.users', string='批准人', copy=False)
    approve_date = fields.Datetime(string='生效时间', copy=False)
    prev_card_id = fields.Many2one('sn.inj.process.card', string='上一版本', copy=False)
    monitored_count = fields.Integer(string='监控参数数', compute='_compute_monitored')

    @api.depends('version')
    def _compute_version_label(self):
        for card in self:
            card.version_label = 'V%s' % (card.version or 1)

    @api.depends('name', 'version_label', 'product_id')
    def _compute_display_name(self):
        for card in self:
            card.display_name = '%s %s' % (card.name or '', card.version_label or '')

    @api.depends('mold_id', 'product_id')
    def _compute_cavity(self):
        for card in self:
            card.cavity = card.mold_id._cavity_for(card.product_id) if card.mold_id and card.product_id else 0

    @api.depends('part_weight', 'runner_weight', 'mold_id')
    def _compute_shot_weight(self):
        for card in self:
            card.shot_weight = card.part_weight * (card.mold_id.effective_cavity or 1) + card.runner_weight

    def _compute_monitored(self):
        for card in self:
            card.monitored_count = len(card.line_ids.filtered('monitored'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.process.card') or _('New')
        cards = super().create(vals_list)
        for card in cards.filtered(lambda c: not c.line_ids):
            card.action_load_template()
        return cards

    @api.constrains('state', 'product_id', 'mold_id')
    def _check_single_active(self):
        for card in self.filtered(lambda c: c.state == 'active'):
            others = self.search_count([('id', '!=', card.id), ('state', '=', 'active'),
                                        ('product_id', '=', card.product_id.id),
                                        ('mold_id', '=', card.mold_id.id)])
            if others:
                raise ValidationError(_('产品 %(p)s + 模具 %(m)s 已有生效的工艺卡，同一组合只能有一个生效版本。',
                                        p=card.product_id.display_name, m=card.mold_id.sn))

    def action_load_template(self):
        for card in self:
            existing = set(card.line_ids.mapped('code'))
            card.line_ids = [(0, 0, {'sequence': i * 10, 'category': cat, 'code': code, 'name': name,
                                     'unit': unit, 'monitored': mon})
                             for i, (cat, code, name, unit, mon) in enumerate(PARAM_TEMPLATE)
                             if code not in existing]
        return True

    def _limits(self):
        """{参数代码: (标准, 下限, 上限)}，用于逐模次超限判断。"""
        self.ensure_one()
        return {l.code: (l.std_value, l.lower, l.upper) for l in self.line_ids
                if l.monitored and (l.lower or l.upper)}

    @api.model
    def _active_for(self, product, mold):
        return self.search([('product_id', '=', product.id), ('mold_id', '=', mold.id),
                            ('state', '=', 'active')], limit=1)

    # 审批流 ------------------------------------------------------------
    def action_submit(self):
        for card in self:
            if card.state != 'draft':
                raise UserError(_('只有草稿可以提交审核。'))
            bad = card.line_ids.filtered(lambda l: l.lower > l.std_value or l.std_value > l.upper)
            if bad:
                raise UserError(_('参数「%s」标准值不在上下限之间。', bad[0].name))
            card.write({'state': 'review', 'submit_user_id': self.env.user.id,
                        'submit_date': fields.Datetime.now()})
        return True

    def action_approve(self):
        for card in self:
            if card.state != 'review':
                raise UserError(_('只有审核中的工艺卡可以批准生效。'))
            old = self.search([('id', '!=', card.id), ('state', '=', 'active'),
                               ('product_id', '=', card.product_id.id), ('mold_id', '=', card.mold_id.id)])
            old.write({'state': 'obsolete'})
            for o in old:
                o.message_post(body=_('被新版本 %s 替代，自动作废。', card.display_name))
            card.write({'state': 'active', 'approve_user_id': self.env.user.id,
                        'approve_date': fields.Datetime.now()})
        return True

    def action_reject(self):
        self.filtered(lambda c: c.state == 'review').write({'state': 'draft'})
        return True

    def action_obsolete(self):
        self.write({'state': 'obsolete'})
        return True

    def action_new_version(self):
        self.ensure_one()
        top = self.search([('product_id', '=', self.product_id.id), ('mold_id', '=', self.mold_id.id)],
                          order='version desc', limit=1)
        new = self.copy({'version': (top.version or 1) + 1, 'prev_card_id': self.id,
                         'change_note': False})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': new.id,
                'view_mode': 'form'}


class SnInjProcessCardLine(models.Model):
    _name = 'sn.inj.process.card.line'
    _description = '工艺卡参数'
    _order = 'card_id, sequence, id'

    card_id = fields.Many2one('sn.inj.process.card', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    category = fields.Selection(PARAM_CATEGORIES, string='类别', required=True)
    code = fields.Char(string='参数代码', required=True)
    name = fields.Char(string='参数', required=True)
    unit = fields.Char(string='单位')
    std_value = fields.Float(string='标准值', digits=(10, 2))
    lower = fields.Float(string='下限', digits=(10, 2))
    upper = fields.Float(string='上限', digits=(10, 2))
    window_text = fields.Char(string='工艺窗口', compute='_compute_window')
    monitored = fields.Boolean(string='逐模监控')

    @api.depends('std_value', 'lower', 'upper')
    def _compute_window(self):
        for line in self:
            line.window_text = '%g ~ %g' % (line.lower, line.upper) if (line.lower or line.upper) else ''
