from odoo import _, api, fields, models
from odoo.exceptions import UserError

CHANGE_REASONS = [
    ('plan', '计划换产'),
    ('maint', '模具保养'),
    ('fault', '模具故障维修'),
    ('seal', '封穴处理'),
    ('trial', '试模/工程变更'),
    ('life', '寿命到期下机'),
]
CHANGE_TYPES = [('swap', '换模（下旧上新）'), ('mount', '上模'), ('unmount', '下模'), ('remount', '下模维修后复装')]

DEFAULT_STEPS = [
    ('external', '确认下一工单、工艺卡与首件样板'),
    ('external', '模具出库、外观与水路检查'),
    ('external', '模具预热（模温机预接）'),
    ('external', '原料烘干 / 配色备料到位'),
    ('external', '吊具、快速夹模器、工具车就位'),
    ('internal', '最后一模合格品，停机清料'),
    ('internal', '拆水电气管路、下旧模'),
    ('internal', '吊装新模、定位圈对中锁模'),
    ('internal', '接水路/热流道/顶出，调模厚与开合模'),
    ('internal', '调用标准工艺卡，试打调机'),
]
FAI_ITEMS = [
    ('appearance', '外观：无缩水、飞边、缺料、银纹、黑点', ''),
    ('dimension', '关键尺寸 1', 'mm'),
    ('dimension', '关键尺寸 2', 'mm'),
    ('weight', '单件重量', 'g'),
    ('function', '装配/卡扣试装', ''),
]


class SnInjMoldChange(models.Model):
    """换模单（SMED）：内/外部作业分开计时；换模时长口径 = 上一产品最后合格品 → 新产品首件合格。
    「换模完成」时自动上/下模并发起首件检验，首件判合格后换模单才完成，机台方可批量报工。"""
    _name = 'sn.inj.mold.change'
    _description = '换模单'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'planned_start desc, id desc'

    name = fields.Char(string='换模单号', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    machine_id = fields.Many2one('sn.inj.machine', string='机台', required=True, tracking=True, index=True)
    change_type = fields.Selection(CHANGE_TYPES, string='类型', default='swap', required=True)
    mold_out_id = fields.Many2one('sn.inj.mold', string='换下模具', tracking=True)
    mold_in_id = fields.Many2one('sn.inj.mold', string='换上模具', tracking=True)
    plan_id = fields.Many2one('sn.inj.plan', string='对应排产', index=True)
    reason = fields.Selection(CHANGE_REASONS, string='换模原因', default='plan', required=True)
    reason_note = fields.Char(string='原因说明')
    leader_id = fields.Many2one('hr.employee', string='换模组长')
    planned_start = fields.Datetime(string='计划开始', required=True, default=fields.Datetime.now)
    planned_end = fields.Datetime(string='计划结束')
    actual_start = fields.Datetime(string='实际开始(末件合格)')
    mounted_at = fields.Datetime(string='装模完成')
    actual_end = fields.Datetime(string='实际结束(首件合格)')
    step_ids = fields.One2many('sn.inj.mold.change.step', 'change_id', string='作业步骤')
    external_minutes = fields.Float(string='外部作业(分钟)', compute='_compute_minutes', store=True)
    internal_minutes = fields.Float(string='内部作业(分钟)', compute='_compute_minutes', store=True)
    duration_minutes = fields.Float(string='换模时长(分钟)', compute='_compute_minutes', store=True,
                                    aggregator='avg')
    target_minutes = fields.Float(string='SMED 目标(分钟)', default=45)
    over_target = fields.Boolean(string='超目标', compute='_compute_minutes', store=True)
    fai_id = fields.Many2one('sn.inj.fai', string='首件检验', copy=False)
    fai_result = fields.Selection(related='fai_id.result', string='首件结果', store=True)
    state = fields.Selection(
        [('draft', '计划'), ('in_progress', '换模中'), ('fai', '首件确认中'), ('done', '已完成'), ('cancel', '已取消')],
        string='状态', default='draft', required=True, tracking=True)
    note = fields.Text(string='备注')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.mold.change') or _('New')
            if not vals.get('step_ids'):
                vals['step_ids'] = [(0, 0, {'sequence': i, 'step_type': t, 'name': n})
                                    for i, (t, n) in enumerate(DEFAULT_STEPS)]
        return super().create(vals_list)

    @api.depends('step_ids.minutes', 'step_ids.step_type', 'actual_start', 'actual_end', 'target_minutes')
    def _compute_minutes(self):
        for rec in self:
            rec.external_minutes = sum(rec.step_ids.filtered(lambda s: s.step_type == 'external').mapped('minutes'))
            rec.internal_minutes = sum(rec.step_ids.filtered(lambda s: s.step_type == 'internal').mapped('minutes'))
            if rec.actual_start and rec.actual_end:
                rec.duration_minutes = round((rec.actual_end - rec.actual_start).total_seconds() / 60.0, 1)
            else:
                rec.duration_minutes = 0.0
            rec.over_target = bool(rec.duration_minutes and rec.target_minutes and rec.duration_minutes > rec.target_minutes)

    @api.onchange('machine_id')
    def _onchange_machine(self):
        if self.machine_id and not self.mold_out_id:
            self.mold_out_id = self.machine_id.current_mold_id

    def action_start(self, when=None):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('只有计划状态的换模单可以开始。'))
            if rec.mold_out_id and rec.machine_id.current_mold_id != rec.mold_out_id:
                raise UserError(_('机台 %(mc)s 当前模具不是 %(m)s。', mc=rec.machine_id.code, m=rec.mold_out_id.sn))
            when = when or fields.Datetime.now()
            rec.write({'state': 'in_progress', 'actual_start': when})
            rec.machine_id._set_run_state('changeover', _('换模 %s', rec.name), when)
        return True

    def action_mounted(self, when=None):
        """换模完成：执行下旧模/上新模（沿用工装状态机，保养逾期/寿命到期在此拦截），并自动发起首件检验。"""
        for rec in self:
            if rec.state != 'in_progress':
                raise UserError(_('只有换模中的单据可以确认换模完成。'))
            when = when or fields.Datetime.now()
            if rec.mold_out_id:
                rec.mold_out_id._unmount()
            if rec.mold_in_id:
                rec.mold_in_id._mount(rec.machine_id)
                fai = self.env['sn.inj.fai'].create({
                    'change_id': rec.id, 'machine_id': rec.machine_id.id, 'mold_id': rec.mold_in_id.id,
                    'plan_id': rec.plan_id.id,
                    'product_id': (rec.plan_id.product_id or rec.mold_in_id.product_line_ids[:1].product_id).id,
                    'request_time': when,
                })
                rec.write({'state': 'fai', 'mounted_at': when, 'fai_id': fai.id})
                rec.machine_id._set_run_state('changeover', _('等待首件确认 %s', fai.name), when)
            else:
                rec.write({'state': 'done', 'mounted_at': when, 'actual_end': when})
                rec.machine_id._set_run_state('planned_stop', rec.reason_note or _('模具下机'), when)
        return True

    def _on_fai_passed(self, when):
        for rec in self.filtered(lambda r: r.state == 'fai'):
            rec.write({'state': 'done', 'actual_end': when})
            rec.machine_id._set_run_state('running', False, when)
            if rec.plan_id and rec.plan_id.state == 'confirmed':
                rec.plan_id.action_start()

    def action_cancel(self):
        self.filtered(lambda r: r.state == 'draft').write({'state': 'cancel'})
        return True

    def action_open_fai(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sn.inj.fai', 'res_id': self.fai_id.id,
                'view_mode': 'form'}


class SnInjMoldChangeStep(models.Model):
    _name = 'sn.inj.mold.change.step'
    _description = '换模作业步骤'
    _order = 'change_id, sequence, id'

    change_id = fields.Many2one('sn.inj.mold.change', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    step_type = fields.Selection([('external', '外部作业（不停机）'), ('internal', '内部作业（停机）')],
                                 string='作业类型', required=True, default='internal')
    name = fields.Char(string='作业内容', required=True)
    minutes = fields.Float(string='用时(分钟)')
    done = fields.Boolean(string='完成')


class SnInjFai(models.Model):
    """注塑首件检验：换模完成自动发起；判合格前该机台该模具不能批量报工。"""
    _name = 'sn.inj.fai'
    _description = '注塑首件检验'
    _inherit = ['mail.thread']
    _order = 'request_time desc, id desc'

    name = fields.Char(string='首件单号', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    change_id = fields.Many2one('sn.inj.mold.change', string='换模单', index=True)
    machine_id = fields.Many2one('sn.inj.machine', string='机台', required=True, index=True)
    mold_id = fields.Many2one('sn.inj.mold', string='模具', required=True, index=True)
    plan_id = fields.Many2one('sn.inj.plan', string='排产计划')
    product_id = fields.Many2one('product.product', string='产品')
    request_time = fields.Datetime(string='发起时间', default=fields.Datetime.now)
    judge_time = fields.Datetime(string='判定时间')
    inspector_id = fields.Many2one('hr.employee', string='检验员')
    item_ids = fields.One2many('sn.inj.fai.item', 'fai_id', string='检验项目')
    image = fields.Image(string='首件照片', max_width=1024, max_height=1024)
    result = fields.Selection([('pending', '待判定'), ('pass', '合格'), ('fail', '不合格')],
                              string='判定结果', default='pending', required=True, tracking=True)
    note = fields.Char(string='说明')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.fai') or _('New')
            if not vals.get('item_ids'):
                vals['item_ids'] = [(0, 0, {'sequence': i, 'item_type': t, 'name': n, 'unit': u})
                                    for i, (t, n, u) in enumerate(FAI_ITEMS)]
        return super().create(vals_list)

    def action_pass(self, when=None):
        when = when or fields.Datetime.now()
        for fai in self:
            if fai.item_ids.filtered(lambda i: i.result == 'ng'):
                raise UserError(_('存在不合格检验项，不能判定合格。'))
            fai.write({'result': 'pass', 'judge_time': when})
            fai.change_id._on_fai_passed(when)
        return True

    def action_fail(self, when=None):
        for fai in self:
            fai.write({'result': 'fail', 'judge_time': when or fields.Datetime.now()})
            fai.message_post(body=_('首件不合格，请调机后重新送检。'))
        return True

    def action_retest(self):
        self.filtered(lambda f: f.result == 'fail').write({'result': 'pending', 'judge_time': False})
        return True

    @api.model
    def _gate_ok(self, machine, mold, at=None):
        """批量报工闸门：该机台+模具最近一次首件必须为合格（无换模记录的历史在机模具视为已放行）。"""
        domain = [('machine_id', '=', machine.id), ('mold_id', '=', mold.id)]
        if at:
            domain.append(('request_time', '<=', at))
        last = self.search(domain, order='request_time desc, id desc', limit=1)
        return (not last) or last.result == 'pass', last


class SnInjFaiItem(models.Model):
    _name = 'sn.inj.fai.item'
    _description = '首件检验项目'
    _order = 'fai_id, sequence, id'

    fai_id = fields.Many2one('sn.inj.fai', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    item_type = fields.Selection([('appearance', '外观'), ('dimension', '尺寸'), ('weight', '重量'),
                                  ('function', '功能')], string='类型', default='dimension')
    name = fields.Char(string='检验项目', required=True)
    unit = fields.Char(string='单位')
    std_value = fields.Float(string='标准值', digits=(10, 3))
    lower = fields.Float(string='下限', digits=(10, 3))
    upper = fields.Float(string='上限', digits=(10, 3))
    measured = fields.Float(string='实测值', digits=(10, 3))
    result = fields.Selection([('ok', '合格'), ('ng', '不合格')], string='结果')
