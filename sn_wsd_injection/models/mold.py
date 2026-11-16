from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MOLD_STATES = [
    ('in_stock', '在库'),
    ('on_machine', '在机'),
    ('maintaining', '保养中'),
    ('repairing', '维修中'),
    ('sealed', '封存'),
    ('scrapped', '报废'),
]
# 工装通用状态 → 模具状态
TOOLING_TO_MOLD = {
    'idle': 'in_stock',
    'issued': 'in_stock',
    'online': 'on_machine',
    'maintaining': 'maintaining',
    'repairing': 'repairing',
    'disabled': 'sealed',
    'scrapped': 'scrapped',
}
MOLD_TYPE_CODE = 'MOLD'


class SnInjMold(models.Model):
    """模具台账。

    模具是「工装」的一个类型：委托继承 sn.tooling（工装编号、库位、累计/周期使用次数、
    保养与报废状态、领用/上线/保养/维修/停用/报废生命周期和履历全部沿用），
    这里只扩展注塑专属的穴数/封穴、寿命与保养模次、适用吨位、水口重、标准周期等。
    模次 = 工装的使用次数：报工时调用 sn.tooling.register_usage() 累加。
    """
    _name = 'sn.inj.mold'
    _description = '注塑模具'
    _inherits = {'sn.tooling': 'tooling_id'}
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tooling_id'

    tooling_id = fields.Many2one('sn.tooling', string='工装', required=True,
                                 ondelete='cascade', index=True)
    name = fields.Char(string='模具名称', required=True, tracking=True)
    mold_kind = fields.Selection(
        [('single', '单穴模'), ('multi', '一模多穴'), ('family', '家族模（一模多品）')],
        string='模具结构', default='multi', required=True)
    product_line_ids = fields.One2many('sn.inj.mold.product', 'mold_id', string='产品与穴数')
    product_ids = fields.Many2many('product.product', compute='_compute_products',
                                   string='产品', search='_search_product_ids')
    product_names = fields.Char(string='产品清单', compute='_compute_products')
    seal_ids = fields.One2many('sn.inj.mold.seal', 'mold_id', string='封穴记录')
    design_cavity = fields.Integer(string='设计穴数', compute='_compute_cavity', store=True)
    sealed_cavity = fields.Integer(string='封穴数', compute='_compute_cavity', store=True)
    effective_cavity = fields.Integer(string='有效穴数', compute='_compute_cavity', store=True)
    cavity_text = fields.Char(string='穴数', compute='_compute_cavity', store=True)
    # 寿命/保养（数值存放在工装模板上，沿用工装的保养/报废状态计算）
    design_life = fields.Integer(related='template_id.scrap_count_limit', readonly=False,
                                 string='设计寿命(模次)')
    maint_cycle = fields.Integer(related='template_id.maintenance_count_limit', readonly=False,
                                 string='保养周期(模次)')
    maint_remind = fields.Integer(related='template_id.maintenance_count_reminder', readonly=False,
                                  string='提前预警(模次)')
    mold_supplier_id = fields.Many2one(related='template_id.supplier_id', readonly=False,
                                       string='模具供应商')
    maint_remaining = fields.Integer(string='距下次保养(模次)', compute='_compute_progress', store=True)
    maint_progress = fields.Float(string='保养进度(%)', compute='_compute_progress', store=True)
    life_progress = fields.Float(string='寿命进度(%)', compute='_compute_progress', store=True)
    life_remaining = fields.Integer(string='剩余寿命(模次)', compute='_compute_progress', store=True)
    warn_level = fields.Selection(
        [('normal', '正常'), ('warn', '预警'), ('danger', '超限')],
        string='预警等级', compute='_compute_progress', store=True)
    warn_text = fields.Char(string='预警说明', compute='_compute_progress', store=True)
    mold_state = fields.Selection(MOLD_STATES, string='模具状态', compute='_compute_mold_state',
                                  store=True, index=True)
    machine_id = fields.Many2one('sn.inj.machine', string='当前机台', copy=False, tracking=True)
    tonnage_min = fields.Integer(string='适用吨位下限(T)')
    tonnage_max = fields.Integer(string='适用吨位上限(T)')
    runner_weight = fields.Float(string='水口重(g/模)')
    std_cycle = fields.Float(string='标准周期(s)')
    grade_id = fields.Many2one('sn.inj.material.grade', string='适用料种')
    steel = fields.Char(string='模仁钢材')
    gate_type = fields.Selection(
        [('hot_valve', '热流道针阀'), ('hot_open', '热流道开放式'), ('pin', '点浇口'),
         ('sub', '潜伏式浇口'), ('side', '侧浇口')], string='浇口形式')
    mold_size = fields.Char(string='外形尺寸(mm)')
    mold_weight = fields.Float(string='模具重量(kg)')
    first_article_image = fields.Image(string='首件图片', max_width=1024, max_height=1024)
    maint_task_ids = fields.One2many('sn.inj.mold.maint', 'mold_id', string='保养任务')
    maint_task_count = fields.Integer(compute='_compute_counts')
    change_count = fields.Integer(compute='_compute_counts')
    note = fields.Text(string='备注')

    # ------------------------------------------------------------------
    @api.depends('sn', 'name')
    def _compute_display_name(self):
        short = self.env.context.get('inj_mold_short')
        for mold in self:
            mold.display_name = mold.sn if short else '%s %s' % (mold.sn or '', mold.name or '')

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        if name:
            domain = list(domain or []) + ['|', ('sn', operator, name), ('name', operator, name)]
            return super().name_search('', domain=domain, operator='ilike', limit=limit)
        return super().name_search(name, domain=domain, operator=operator, limit=limit)

    @api.depends('product_line_ids.product_id')
    def _compute_products(self):
        for mold in self:
            mold.product_ids = mold.product_line_ids.product_id
            mold.product_names = '、'.join(mold.product_line_ids.product_id.mapped('name'))

    def _search_product_ids(self, operator, value):
        lines = self.env['sn.inj.mold.product'].search([('product_id', operator, value)])
        return [('id', 'in', lines.mold_id.ids)]

    @api.depends('product_line_ids.cavity_qty', 'seal_ids.is_active')
    def _compute_cavity(self):
        for mold in self:
            design = sum(mold.product_line_ids.mapped('cavity_qty'))
            sealed = len(mold.seal_ids.filtered('is_active'))
            mold.design_cavity = design
            mold.sealed_cavity = sealed
            mold.effective_cavity = max(design - sealed, 0)
            if len(mold.product_line_ids) > 1:
                mold.cavity_text = '+'.join(str(n) for n in mold.product_line_ids.mapped('cavity_qty'))
            else:
                mold.cavity_text = '1×%s' % design
            if sealed:
                mold.cavity_text += _('（封 %s）', sealed)

    @api.depends('total_usage_count', 'cycle_usage_count', 'template_id.scrap_count_limit',
                 'template_id.maintenance_count_limit', 'template_id.maintenance_count_reminder')
    def _compute_progress(self):
        for mold in self:
            cycle = mold.template_id.maintenance_count_limit
            life = mold.template_id.scrap_count_limit
            remind = mold.template_id.maintenance_count_reminder
            mold.maint_remaining = (cycle - mold.cycle_usage_count) if cycle else 0
            mold.maint_progress = min(mold.cycle_usage_count * 100.0 / cycle, 100.0) if cycle else 0.0
            mold.life_remaining = max(life - mold.total_usage_count, 0) if life else 0
            mold.life_progress = min(mold.total_usage_count * 100.0 / life, 100.0) if life else 0.0
            level, texts = 'normal', []
            if cycle and mold.cycle_usage_count >= cycle:
                level = 'danger'
                texts.append(_('保养已超期'))
            elif cycle and mold.maint_remaining <= (remind or cycle * 0.1):
                level = 'warn'
                texts.append(_('临近保养'))
            if life and mold.life_progress >= 100:
                level = 'danger'
                texts.append(_('寿命到期'))
            elif life and mold.life_progress >= 95:
                level = 'danger'
                texts.append(_('接近寿命'))
            elif life and mold.life_progress >= 90:
                level = 'danger' if level == 'danger' else 'warn'
                texts.append(_('接近寿命'))
            mold.warn_level = level
            mold.warn_text = '、'.join(texts)

    @api.depends('tooling_id.state')
    def _compute_mold_state(self):
        for mold in self:
            mold.mold_state = TOOLING_TO_MOLD.get(mold.tooling_id.state, 'in_stock')

    def _compute_counts(self):
        Change = self.env['sn.inj.mold.change']
        for mold in self:
            mold.maint_task_count = len(mold.maint_task_ids)
            mold.change_count = Change.search_count(['|', ('mold_in_id', '=', mold.id), ('mold_out_id', '=', mold.id)])

    # ------------------------------------------------------------------
    @api.model
    def _mold_tooling_type(self):
        ttype = self.env['sn.tooling.type'].search(
            [('code', '=', MOLD_TYPE_CODE), ('company_id', '=', self.env.company.id)], limit=1)
        if not ttype:
            ttype = self.env['sn.tooling.type'].create({'name': '注塑模具', 'code': MOLD_TYPE_CODE})
        return ttype

    @api.model_create_multi
    def create(self, vals_list):
        Template = self.env['sn.tooling.template']
        for vals in vals_list:
            if not vals.get('tooling_id') and not vals.get('template_id'):
                template = Template.create({
                    'code': vals.get('sn'),
                    'name': vals.get('name'),
                    'type_id': self._mold_tooling_type().id,
                    'maintenance_by_count': True,
                    'maintenance_count_limit': vals.pop('maint_cycle', 0) or 0,
                    'maintenance_count_reminder': vals.pop('maint_remind', 0) or 0,
                    'scrap_count_limit': vals.pop('design_life', 0) or 0,
                    'supplier_id': vals.pop('mold_supplier_id', False),
                })
                vals['template_id'] = template.id
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # 穴数
    # ------------------------------------------------------------------
    def _cavity_for(self, product, at=None):
        """某产品在指定时刻的有效穴数 = 设计穴数 − 当时生效的封穴数。"""
        self.ensure_one()
        at = at or fields.Datetime.now()
        line = self.product_line_ids.filtered(lambda l: l.product_id == product)[:1]
        if not line:
            return 0
        seals = self.seal_ids.filtered(
            lambda s: (not s.product_id or s.product_id == product)
            and s.date_seal and s.date_seal <= at
            and (not s.date_unseal or s.date_unseal > at))
        return max(line.cavity_qty - len(seals), 0)

    # ------------------------------------------------------------------
    # 上/下机（沿用工装：领用 → 上线 / 下线 → 归还）
    # ------------------------------------------------------------------
    def _mount(self, machine):
        for mold in self:
            tooling = mold.tooling_id.sudo()
            if mold.mold_state != 'in_stock':
                raise UserError(_('模具 %(m)s 当前状态为「%(s)s」，不能上机。', m=mold.sn,
                                  s=dict(MOLD_STATES).get(mold.mold_state)))
            mold._check_usable(_('上机'))
            if machine.tonnage and (mold.tonnage_min and machine.tonnage < mold.tonnage_min
                                    or mold.tonnage_max and machine.tonnage > mold.tonnage_max):
                raise UserError(_('机台 %(mc)s（%(t)sT）不在模具 %(m)s 适用吨位 %(a)s–%(b)sT 范围内。',
                                  mc=machine.code, t=machine.tonnage, m=mold.sn,
                                  a=mold.tonnage_min, b=mold.tonnage_max))
            if tooling.state == 'idle':
                tooling.action_issue()       # 保养超期的模具会在此被拦截（工装规则）
            tooling.action_online()
            mold.machine_id = machine
            machine.current_mold_id = mold
        return True

    def _unmount(self):
        for mold in self:
            tooling = mold.tooling_id.sudo()
            if tooling.state == 'online':
                tooling.action_offline()
            if tooling.state == 'issued':
                tooling.action_return()
            if mold.machine_id and mold.machine_id.current_mold_id == mold:
                mold.machine_id.current_mold_id = False
            mold.machine_id = False
        return True

    def _check_usable(self, action):
        """保养逾期 / 寿命到期的模具禁止排产、上机。"""
        for mold in self:
            if mold.design_life and mold.total_usage_count >= mold.design_life:
                raise UserError(_('模具 %(m)s 已达设计寿命（%(n)s 模次），禁止%(a)s，请走报废/翻新评审。',
                                  m=mold.sn, n=mold.design_life, a=action))
            if mold.maintenance_status == 'expired':
                raise UserError(_('模具 %(m)s 保养已逾期（周期模次 %(c)s / %(p)s），禁止%(a)s，请先完成保养。',
                                  m=mold.sn, c=mold.cycle_usage_count, p=mold.maint_cycle, a=action))
        return True

    def _register_shots(self, shots):
        """报工累加模次：调用工装 register_usage（在机校验 + 寿命硬上限）。"""
        for mold in self:
            if shots > 0:
                mold.tooling_id.sudo().register_usage(int(shots))
        return True

    # ------------------------------------------------------------------
    # 按钮
    # ------------------------------------------------------------------
    def action_seal_mold(self):
        for mold in self:
            if mold.machine_id:
                raise UserError(_('请先下机再封存。'))
            mold.tooling_id.sudo().action_disable(reason=_('长期不排产，封存入库'))
        return True

    def action_unseal_mold(self):
        self.tooling_id.sudo().action_enable()
        return True

    def action_create_maint(self):
        self.ensure_one()
        task = self.env['sn.inj.mold.maint'].create({
            'mold_id': self.id, 'trigger': 'manual', 'level': 'l1',
            'shots_at_trigger': self.cycle_usage_count,
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'sn.inj.mold.maint',
                'res_id': task.id, 'view_mode': 'form'}

    def action_view_maint(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('保养任务'),
                'res_model': 'sn.inj.mold.maint', 'view_mode': 'list,form',
                'domain': [('mold_id', '=', self.id)], 'context': {'default_mold_id': self.id}}

    def action_view_changes(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('换模记录'),
                'res_model': 'sn.inj.mold.change', 'view_mode': 'list,form',
                'domain': ['|', ('mold_in_id', '=', self.id), ('mold_out_id', '=', self.id)]}

    def action_view_tooling_records(self):
        self.ensure_one()
        return self.tooling_id.action_view_records()


class SnInjMoldProduct(models.Model):
    _name = 'sn.inj.mold.product'
    _description = '模具产品穴数'
    _order = 'mold_id, sequence, id'

    sequence = fields.Integer(default=10)
    mold_id = fields.Many2one('sn.inj.mold', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='产品', required=True)
    cavity_qty = fields.Integer(string='设计穴数', required=True, default=1)
    sealed_qty = fields.Integer(string='封穴数', compute='_compute_effective')
    effective_qty = fields.Integer(string='有效穴数', compute='_compute_effective')
    part_weight = fields.Float(string='单件重(g)')

    @api.depends('cavity_qty', 'mold_id.seal_ids.is_active', 'mold_id.seal_ids.product_id')
    def _compute_effective(self):
        for line in self:
            seals = line.mold_id.seal_ids.filtered(
                lambda s: s.is_active and (not s.product_id or s.product_id == line.product_id))
            line.sealed_qty = len(seals)
            line.effective_qty = max(line.cavity_qty - len(seals), 0)


class SnInjMoldSeal(models.Model):
    """封穴（堵穴）记录：封穴期间有效穴数减少，产量按有效穴数核算。"""
    _name = 'sn.inj.mold.seal'
    _description = '模具封穴记录'
    _order = 'date_seal desc, id desc'

    mold_id = fields.Many2one('sn.inj.mold', string='模具', required=True, ondelete='cascade', index=True)
    cavity_no = fields.Char(string='穴号', required=True)
    product_id = fields.Many2one('product.product', string='产品')
    reason = fields.Char(string='封穴原因', required=True)
    date_seal = fields.Datetime(string='封穴时间', required=True, default=fields.Datetime.now)
    date_unseal = fields.Datetime(string='解封时间')
    user_id = fields.Many2one('res.users', string='确认人', default=lambda self: self.env.user)
    is_active = fields.Boolean(string='封穴中', compute='_compute_active', store=True)

    @api.depends('date_unseal')
    def _compute_active(self):
        for seal in self:
            seal.is_active = not seal.date_unseal

    @api.constrains('mold_id', 'cavity_no', 'is_active')
    def _check_dup(self):
        for seal in self.filtered('is_active'):
            dup = self.search_count([('mold_id', '=', seal.mold_id.id), ('cavity_no', '=', seal.cavity_no),
                                     ('is_active', '=', True), ('id', '!=', seal.id)])
            if dup:
                raise ValidationError(_('穴号 %s 已处于封穴状态。', seal.cavity_no))

    def action_unseal(self):
        self.filtered('is_active').write({'date_unseal': fields.Datetime.now()})
        return True


MAINT_LEVELS = [('l1', '一级保养'), ('l2', '二级保养'), ('overhaul', '大修/翻新')]
MAINT_ITEMS = {
    'l1': ['分型面/排气槽清洁', '顶针、斜顶、滑块润滑', '水路通畅与漏水检查', '型腔表面防锈处理'],
    'l2': ['分型面/排气槽清洁', '顶针、斜顶、滑块拆检润滑', '水路除垢与保压测试',
           '导柱导套磨损检查', '热流道加热圈/感温线检测', '弹簧/易损件更换', '型腔抛光与尺寸复核'],
    'overhaul': ['全拆清洗', '型芯/型腔修复', '易损件全部更换', '试模验证'],
}


class SnInjMoldMaint(models.Model):
    """模具保养任务：按模次阈值由定时任务自动生成，也可手工/异常触发。
    执行沿用工装两段式保养（保养开始 → 保养完成，完成时清零周期模次）。"""
    _name = 'sn.inj.mold.maint'
    _description = '模具保养任务'
    _inherit = ['mail.thread']
    _order = 'plan_date desc, id desc'

    name = fields.Char(string='任务编号', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    mold_id = fields.Many2one('sn.inj.mold', string='模具', required=True, index=True, tracking=True)
    machine_id = fields.Many2one(related='mold_id.machine_id', string='当前机台')
    level = fields.Selection(MAINT_LEVELS, string='保养级别', default='l1', required=True)
    trigger = fields.Selection(
        [('shot', '模次触发'), ('calendar', '周期触发'), ('manual', '手工/异常')],
        string='触发方式', default='shot', required=True)
    shots_at_trigger = fields.Integer(string='触发时周期模次')
    maint_cycle = fields.Integer(related='mold_id.maint_cycle', string='保养周期(模次)')
    plan_date = fields.Date(string='计划日期', default=fields.Date.context_today)
    date_start = fields.Datetime(string='开始时间')
    date_done = fields.Datetime(string='完成时间')
    hours = fields.Float(string='工时(h)')
    cost = fields.Float(string='费用(元)')
    user_id = fields.Many2one('hr.employee', string='模修负责人')
    item_ids = fields.One2many('sn.inj.mold.maint.item', 'task_id', string='保养项目')
    state = fields.Selection(
        [('todo', '待保养'), ('doing', '保养中'), ('done', '已完成'), ('cancel', '已取消')],
        string='状态', default='todo', required=True, tracking=True)
    note = fields.Text(string='保养记录')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.mold.maint') or _('New')
            if not vals.get('item_ids'):
                vals['item_ids'] = [(0, 0, {'sequence': i, 'name': n})
                                    for i, n in enumerate(MAINT_ITEMS[vals.get('level') or 'l1'])]
        return super().create(vals_list)

    def action_start(self, when=None):
        for task in self:
            if task.state != 'todo':
                raise UserError(_('只有待保养的任务可以开始。'))
            if task.mold_id.machine_id:
                raise UserError(_('模具 %(m)s 仍在机台 %(mc)s 上，请先换模下机。',
                                  m=task.mold_id.sn, mc=task.mold_id.machine_id.code))
            task.mold_id.tooling_id.sudo().action_maintain_start()
            task.write({'state': 'doing', 'date_start': when or fields.Datetime.now()})
        return True

    def action_done(self, when=None):
        for task in self:
            if task.state != 'doing':
                raise UserError(_('只有保养中的任务可以完成。'))
            line_vals = [(0, 0, {'sequence': item.sequence, 'name': item.name,
                                 'result': 'issue' if item.result == 'abnormal' else 'done',
                                 'note': item.note}) for item in task.item_ids]
            task.mold_id.tooling_id.sudo().action_maintain_done(line_vals=line_vals)
            task.write({'state': 'done', 'date_done': when or fields.Datetime.now()})
        return True

    def action_cancel(self):
        self.filtered(lambda t: t.state == 'todo').write({'state': 'cancel'})
        return True

    @api.model
    def _cron_generate(self):
        """模次到达「保养周期 − 提前预警」时自动生成保养任务（每套模具只保留一张未完成任务）。"""
        molds = self.env['sn.inj.mold'].search([('maint_cycle', '>', 0),
                                                ('mold_state', 'not in', ('scrapped', 'sealed'))])
        created = self.browse()
        for mold in molds:
            threshold = mold.maint_cycle - (mold.maint_remind or int(mold.maint_cycle * 0.1))
            if mold.cycle_usage_count < threshold:
                continue
            if self.search_count([('mold_id', '=', mold.id), ('state', 'in', ('todo', 'doing'))]):
                continue
            level = 'l2' if mold.total_usage_count and mold.maint_cycle and \
                (mold.total_usage_count // mold.maint_cycle) % 4 == 3 else 'l1'
            created |= self.create({'mold_id': mold.id, 'trigger': 'shot', 'level': level,
                                    'shots_at_trigger': mold.cycle_usage_count})
        for task in created:
            task.message_post(body=_('周期模次 %(c)s 已达预警阈值（保养周期 %(p)s），系统自动生成保养任务。',
                                     c=task.shots_at_trigger, p=task.maint_cycle))
        return created


class SnInjMoldMaintItem(models.Model):
    _name = 'sn.inj.mold.maint.item'
    _description = '模具保养项目'
    _order = 'task_id, sequence, id'

    task_id = fields.Many2one('sn.inj.mold.maint', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='保养项目', required=True)
    result = fields.Selection([('ok', '正常'), ('fixed', '已处理'), ('abnormal', '异常')],
                              string='结果', default='ok')
    note = fields.Char(string='说明')
