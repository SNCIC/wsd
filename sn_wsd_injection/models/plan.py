import math
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PLAN_STATES = [
    ('draft', '草稿'),
    ('confirmed', '已下达'),
    ('running', '生产中'),
    ('done', '已完成'),
    ('cancel', '已取消'),
]
GANTT_COLORS = {'draft': 0, 'confirmed': 4, 'running': 10, 'done': 7, 'cancel': 1}


class SnInjPlan(models.Model):
    """注塑排产计划：机台 + 模具 + 产品。
    所需模次 = ⌈计划数量 ÷ 有效穴数⌉，预计工时 = 模次 × 标准周期（取生效工艺卡）。
    校验：同一模具同一时段不能排两台机、同一机台时段不重叠（家族模联产除外）、机台吨位须在模具适用范围内。
    可关联制造订单（mrp.production），甘特视图复用 sn_wsd_gantt，按机台分组。"""
    _name = 'sn.inj.plan'
    _description = '注塑排产计划'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='计划单号', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    production_id = fields.Many2one('mrp.production', string='制造订单', index=True)
    partner_id = fields.Many2one('res.partner', string='客户/需求方')
    product_id = fields.Many2one('product.product', string='产品', required=True, tracking=True)
    mold_id = fields.Many2one('sn.inj.mold', string='模具', required=True, tracking=True,
                              domain="[('product_ids', 'in', [product_id])]")
    machine_id = fields.Many2one('sn.inj.machine', string='机台', required=True, tracking=True, index=True)
    card_id = fields.Many2one('sn.inj.process.card', string='工艺卡',
                              domain="[('product_id', '=', product_id), ('mold_id', '=', mold_id), ('state', '=', 'active')]")
    color_recipe_id = fields.Many2one('sn.inj.color.recipe', string='配色配方')
    planned_qty = fields.Integer(string='计划数量', required=True, tracking=True)
    cavity = fields.Integer(string='有效穴数', compute='_compute_quantities', store=True)
    required_shots = fields.Integer(string='所需模次', compute='_compute_quantities', store=True)
    std_cycle = fields.Float(string='标准周期(s)', compute='_compute_quantities', store=True)
    planned_hours = fields.Float(string='预计工时(h)', compute='_compute_quantities', store=True)
    changeover_minutes = fields.Integer(string='预留换模(分钟)', default=0)
    date_start = fields.Datetime(string='计划开始', required=True, tracking=True)
    date_end = fields.Datetime(string='计划完成', compute='_compute_date_end', store=True)
    date_deadline = fields.Date(string='需求交期')
    date_finished = fields.Datetime(string='实际完工', copy=False)
    gantt_end = fields.Datetime(string='甘特结束', compute='_compute_gantt_end', store=True,
                                help='已完工取实际完工时间，否则取计划完成时间。')
    state = fields.Selection(PLAN_STATES, string='状态', default='draft', required=True, tracking=True, copy=False)
    priority = fields.Selection([('0', '普通'), ('1', '紧急')], string='优先级', default='0')
    report_line_ids = fields.One2many('sn.inj.report.line', 'plan_id', string='报工明细')
    done_shots = fields.Integer(string='已打模次', compute='_compute_progress', store=True)
    good_qty = fields.Integer(string='良品数', compute='_compute_progress', store=True)
    defect_qty = fields.Integer(string='不良数', compute='_compute_progress', store=True)
    progress = fields.Float(string='达成率(%)', compute='_compute_progress', store=True)
    yield_rate = fields.Float(string='良率(%)', compute='_compute_progress', store=True)
    x_gantt_color = fields.Integer(compute='_compute_gantt_color')
    mold_change_ids = fields.One2many('sn.inj.mold.change', 'plan_id', string='换模单')
    note = fields.Text(string='备注')

    @api.depends('name', 'product_id', 'mold_id', 'planned_qty')
    def _compute_display_name(self):
        for plan in self:
            if self.env.context.get('inj_plan_short'):
                plan.display_name = plan.name
            else:
                plan.display_name = '%s · %s · %s' % (plan.mold_id.sn or '', plan.product_id.name or '',
                                                      '{:,}'.format(plan.planned_qty or 0))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.plan') or _('New')
        plans = super().create(vals_list)
        for plan in plans.filtered(lambda p: not p.card_id):
            plan.card_id = self.env['sn.inj.process.card']._active_for(plan.product_id, plan.mold_id)
        return plans

    @api.onchange('product_id', 'mold_id')
    def _onchange_card(self):
        if self.product_id and self.mold_id:
            self.card_id = self.env['sn.inj.process.card']._active_for(self.product_id, self.mold_id)

    @api.depends('planned_qty', 'mold_id', 'mold_id.effective_cavity', 'product_id', 'card_id.std_cycle',
                 'mold_id.std_cycle', 'date_start')
    def _compute_quantities(self):
        for plan in self:
            cavity = plan.mold_id._cavity_for(plan.product_id, plan.date_start) if plan.mold_id and plan.product_id else 0
            plan.cavity = cavity
            plan.required_shots = math.ceil(plan.planned_qty / cavity) if cavity else 0
            plan.std_cycle = plan.card_id.std_cycle or plan.mold_id.std_cycle or 0.0
            plan.planned_hours = round(plan.required_shots * plan.std_cycle / 3600.0, 2)

    @api.depends('date_start', 'planned_hours', 'changeover_minutes')
    def _compute_date_end(self):
        for plan in self:
            plan.date_end = plan.date_start and plan.date_start + timedelta(
                hours=plan.planned_hours, minutes=plan.changeover_minutes or 0)

    @api.depends('date_end', 'date_finished', 'state')
    def _compute_gantt_end(self):
        for plan in self:
            plan.gantt_end = plan.date_finished if plan.state == 'done' and plan.date_finished else plan.date_end

    @api.depends('report_line_ids.good_qty', 'report_line_ids.defect_qty', 'report_line_ids.report_id.shots',
                 'report_line_ids.report_id.state', 'planned_qty')
    def _compute_progress(self):
        for plan in self:
            lines = plan.report_line_ids.filtered(lambda l: l.report_id.state == 'done')
            plan.done_shots = sum(lines.mapped('report_id.shots'))
            plan.good_qty = int(sum(lines.mapped('good_qty')))
            plan.defect_qty = int(sum(lines.mapped('defect_qty')))
            total = plan.good_qty + plan.defect_qty
            plan.progress = min(plan.good_qty * 100.0 / plan.planned_qty, 100.0) if plan.planned_qty else 0.0
            plan.yield_rate = plan.good_qty * 100.0 / total if total else 0.0

    def _compute_gantt_color(self):
        for plan in self:
            plan.x_gantt_color = GANTT_COLORS.get(plan.state, 0)

    # ------------------------------------------------------------------
    # 排产校验
    # ------------------------------------------------------------------
    def _overlap_domain(self):
        self.ensure_one()
        return [('id', '!=', self.id), ('state', 'not in', ('cancel', 'done')),
                ('date_start', '<', self.date_end), ('date_end', '>', self.date_start)]

    @api.constrains('mold_id', 'machine_id', 'date_start', 'planned_qty', 'state')
    def _check_schedule(self):
        for plan in self.filtered(lambda p: p.state not in ('cancel', 'done') and p.date_start and p.date_end):
            mold, machine = plan.mold_id, plan.machine_id
            if mold.mold_state in ('scrapped', 'sealed'):
                raise ValidationError(_('模具 %(m)s 状态为「%(s)s」，不能排产。', m=mold.sn,
                                        s=dict(self.env['sn.inj.mold']._fields['mold_state'].selection).get(mold.mold_state)))
            if plan.state in ('draft', 'confirmed'):
                try:
                    mold._check_usable(_('排产'))
                except UserError as err:
                    raise ValidationError(str(err)) from err
            if machine.tonnage and (mold.tonnage_min and machine.tonnage < mold.tonnage_min
                                    or mold.tonnage_max and machine.tonnage > mold.tonnage_max):
                raise ValidationError(_(
                    '吨位不匹配：机台 %(mc)s 为 %(t)sT，模具 %(m)s 适用 %(a)s–%(b)sT。',
                    mc=machine.code, t=machine.tonnage, m=mold.sn, a=mold.tonnage_min, b=mold.tonnage_max))
            conflict = self.search(plan._overlap_domain() + [('mold_id', '=', mold.id),
                                                             ('machine_id', '!=', machine.id)], limit=1)
            if conflict:
                raise ValidationError(_(
                    '模具冲突：模具 %(m)s 在 %(a)s 至 %(b)s 已排在机台 %(mc)s（%(p)s），同一模具同一时段不能上两台机。',
                    m=mold.sn, a=fields.Datetime.context_timestamp(self, conflict.date_start).strftime('%m-%d %H:%M'),
                    b=fields.Datetime.context_timestamp(self, conflict.date_end).strftime('%m-%d %H:%M'),
                    mc=conflict.machine_id.code, p=conflict.name))
            busy = self.search(plan._overlap_domain() + [('machine_id', '=', machine.id),
                                                         ('mold_id', '!=', mold.id)], limit=1)
            if busy:
                raise ValidationError(_('机台冲突：机台 %(mc)s 在该时段已排 %(p)s（模具 %(m)s）。',
                                        mc=machine.code, p=busy.name, m=busy.mold_id.sn))

    # ------------------------------------------------------------------
    def action_confirm(self):
        for plan in self:
            if plan.state != 'draft':
                raise UserError(_('只有草稿计划可以下达。'))
            if not plan.card_id:
                plan.card_id = self.env['sn.inj.process.card']._active_for(plan.product_id, plan.mold_id)
            if not plan.card_id:
                raise UserError(_('产品 %(p)s + 模具 %(m)s 没有生效的标准工艺卡，不能下达。',
                                  p=plan.product_id.display_name, m=plan.mold_id.sn))
            plan.state = 'confirmed'
        return True

    def action_start(self):
        for plan in self:
            if plan.state != 'confirmed':
                raise UserError(_('只有已下达的计划可以开工。'))
            if plan.machine_id.current_mold_id != plan.mold_id:
                raise UserError(_('机台 %(mc)s 当前模具不是 %(m)s，请先完成换模单。',
                                  mc=plan.machine_id.code, m=plan.mold_id.sn))
            ok, fai = self.env['sn.inj.fai']._gate_ok(plan.machine_id, plan.mold_id)
            if not ok:
                raise UserError(_('首件 %s 尚未判定合格，不能开工批量生产。', fai.name))
            plan.state = 'running'
            plan.machine_id.current_plan_id = plan
            if plan.machine_id.run_state != 'running':
                plan.machine_id._set_run_state('running')
        return True

    def action_done(self, when=None):
        for plan in self.filtered(lambda p: p.state in ('running', 'confirmed')):
            plan.write({'state': 'done', 'date_finished': when or fields.Datetime.now()})
            if plan.machine_id.current_plan_id == plan:
                nxt = self.search([('machine_id', '=', plan.machine_id.id), ('state', '=', 'running'),
                                   ('id', '!=', plan.id)], limit=1)
                plan.machine_id.current_plan_id = nxt
        return True

    def action_cancel(self):
        self.filtered(lambda p: p.state in ('draft', 'confirmed')).write({'state': 'cancel'})
        return True

    def action_reset_draft(self):
        self.filtered(lambda p: p.state == 'cancel').write({'state': 'draft'})
        return True
