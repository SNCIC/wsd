from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .shift import SHIFTS


class SnInjReport(models.Model):
    """按模次报工（按机台 × 班次）：
    总数 = 模次 × 有效穴数（封穴期间自动扣减），良品 = 总数 − 不良（按缺陷代码），
    确认时累加模具模次（工装 register_usage）、自动记水口料产生量（模次 × 水口重）。
    家族模一张报工按产品分行（一模多品联产）。"""
    _name = 'sn.inj.report'
    _description = '注塑模次报工'
    _inherit = ['mail.thread']
    _order = 'report_time desc, id desc'

    name = fields.Char(string='报工单号', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    machine_id = fields.Many2one('sn.inj.machine', string='机台', required=True, index=True)
    mold_id = fields.Many2one('sn.inj.mold', string='模具', required=True, index=True)
    plan_id = fields.Many2one('sn.inj.plan', string='排产计划', index=True)
    product_id = fields.Many2one(related='plan_id.product_id', string='产品', store=True)
    date = fields.Date(string='班次日期', required=True, default=fields.Date.context_today, index=True)
    shift = fields.Selection(SHIFTS, string='班次', required=True, default='day')
    report_time = fields.Datetime(string='报工时间', default=fields.Datetime.now, index=True)
    operator_id = fields.Many2one('hr.employee', string='操作工')
    counter_start = fields.Integer(string='起始计数')
    counter_end = fields.Integer(string='结束计数')
    shots = fields.Integer(string='模次', compute='_compute_shots', store=True, readonly=False)
    line_ids = fields.One2many('sn.inj.report.line', 'report_id', string='产品明细')
    defect_ids = fields.One2many('sn.inj.report.defect', 'report_id', string='不良明细')
    total_qty = fields.Integer(string='产出总数', compute='_compute_totals', store=True)
    defect_qty = fields.Integer(string='不良数', compute='_compute_totals', store=True)
    good_qty = fields.Integer(string='良品数', compute='_compute_totals', store=True)
    yield_rate = fields.Float(string='良率(%)', compute='_compute_totals', store=True, aggregator='avg')
    regrind_kg = fields.Float(string='水口料(kg)', compute='_compute_totals', store=True)
    std_cycle = fields.Float(string='标准周期(s)')
    planned_minutes = fields.Float(string='计划时间(分钟)', default=690)
    downtime_minutes = fields.Float(string='停机(分钟)')
    run_minutes = fields.Float(string='运行(分钟)', compute='_compute_oee', store=True)
    actual_cycle = fields.Float(string='实际平均周期(s)', compute='_compute_oee', store=True, aggregator='avg')
    availability = fields.Float(string='时间开动率(%)', compute='_compute_oee', store=True, aggregator='avg')
    performance = fields.Float(string='性能开动率(%)', compute='_compute_oee', store=True, aggregator='avg')
    quality_rate = fields.Float(string='合格品率(%)', compute='_compute_oee', store=True, aggregator='avg')
    oee = fields.Float(string='OEE(%)', compute='_compute_oee', store=True, aggregator='avg')
    state = fields.Selection([('draft', '草稿'), ('done', '已确认')], string='状态', default='draft', tracking=True)
    note = fields.Char(string='备注')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.report') or _('New')
        reports = super().create(vals_list)
        for rep in reports:
            if not rep.std_cycle:
                rep.std_cycle = rep.plan_id.std_cycle or rep.mold_id.std_cycle
            if not rep.line_ids:
                rep._fill_lines()
        return reports

    def _fill_lines(self):
        """按模具产品行生成明细：家族模每个产品一行，找同机台同模具在产计划。"""
        Plan = self.env['sn.inj.plan']
        for rep in self:
            vals = []
            for pl in rep.mold_id.product_line_ids:
                plan = rep.plan_id if rep.plan_id.product_id == pl.product_id else Plan.search([
                    ('machine_id', '=', rep.machine_id.id), ('mold_id', '=', rep.mold_id.id),
                    ('product_id', '=', pl.product_id.id), ('state', 'in', ('running', 'confirmed', 'done'))],
                    order='date_start desc', limit=1)
                vals.append((0, 0, {'product_id': pl.product_id.id, 'plan_id': plan.id,
                                    'cavity': rep.mold_id._cavity_for(pl.product_id, rep.report_time),
                                    'part_weight': pl.part_weight}))
            rep.line_ids = vals

    @api.depends('counter_start', 'counter_end')
    def _compute_shots(self):
        for rep in self:
            if rep.counter_end and rep.counter_end >= rep.counter_start:
                rep.shots = rep.counter_end - rep.counter_start

    @api.depends('shots', 'line_ids.cavity', 'defect_ids.qty', 'mold_id.runner_weight')
    def _compute_totals(self):
        for rep in self:
            total = rep.shots * sum(rep.line_ids.mapped('cavity'))
            defect = int(sum(rep.defect_ids.mapped('qty')))
            rep.total_qty = total
            rep.defect_qty = defect
            rep.good_qty = total - defect
            rep.yield_rate = (total - defect) * 100.0 / total if total else 0.0
            rep.regrind_kg = round(rep.shots * rep.mold_id.runner_weight / 1000.0, 2)

    @api.depends('shots', 'std_cycle', 'planned_minutes', 'downtime_minutes', 'total_qty', 'good_qty')
    def _compute_oee(self):
        for rep in self:
            run = max(rep.planned_minutes - rep.downtime_minutes, 0)
            rep.run_minutes = run
            rep.actual_cycle = round(run * 60.0 / rep.shots, 2) if rep.shots else 0.0
            rep.availability = run * 100.0 / rep.planned_minutes if rep.planned_minutes else 0.0
            rep.performance = min(rep.shots * rep.std_cycle * 100.0 / (run * 60.0), 100.0) if run else 0.0
            rep.quality_rate = rep.good_qty * 100.0 / rep.total_qty if rep.total_qty else 0.0
            rep.oee = rep.availability * rep.performance * rep.quality_rate / 10000.0

    @api.constrains('defect_ids', 'shots', 'line_ids')
    def _check_defects(self):
        for rep in self:
            for line in rep.line_ids:
                if line.defect_qty > rep.shots * line.cavity:
                    raise ValidationError(_('产品 %s 不良数超过产出数。', line.product_id.display_name))

    def action_done(self):
        for rep in self:
            if rep.state != 'draft':
                continue
            if rep.shots <= 0:
                raise UserError(_('模次必须大于 0。'))
            if rep.machine_id.current_mold_id != rep.mold_id:
                raise UserError(_('机台 %(mc)s 当前在机模具不是 %(m)s，不能按该模具报工。',
                                  mc=rep.machine_id.code, m=rep.mold_id.sn))
            ok, fai = self.env['sn.inj.fai']._gate_ok(rep.machine_id, rep.mold_id, rep.report_time)
            if not ok:
                raise UserError(_('首件 %(f)s 尚未判定合格（当前：%(r)s），不能批量报工。', f=fai.name,
                                  r=dict(fai._fields['result'].selection).get(fai.result)))
            rep.mold_id._register_shots(rep.shots)
            grade = rep.mold_id.grade_id or rep.plan_id.card_id.grade_id
            if rep.regrind_kg and grade:
                self.env['sn.inj.regrind'].create({
                    'move_type': 'generate', 'move_time': rep.report_time, 'grade_id': grade.id,
                    'machine_id': rep.machine_id.id, 'report_id': rep.id, 'qty_kg': rep.regrind_kg,
                    'color_no': rep.plan_id.color_recipe_id.color_no or False,
                })
            rep.state = 'done'
        return True


class SnInjReportLine(models.Model):
    _name = 'sn.inj.report.line'
    _description = '报工产品明细'
    _order = 'report_id, id'

    report_id = fields.Many2one('sn.inj.report', string='报工单', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='产品', required=True)
    plan_id = fields.Many2one('sn.inj.plan', string='排产计划', index=True)
    cavity = fields.Integer(string='有效穴数')
    part_weight = fields.Float(string='单件重(g)')
    total_qty = fields.Integer(string='产出', compute='_compute_qty', store=True)
    defect_qty = fields.Integer(string='不良', compute='_compute_qty', store=True)
    good_qty = fields.Integer(string='良品', compute='_compute_qty', store=True)

    @api.depends('report_id.shots', 'cavity', 'report_id.defect_ids.qty', 'report_id.defect_ids.product_id')
    def _compute_qty(self):
        for line in self:
            total = line.report_id.shots * line.cavity
            defect = int(sum(line.report_id.defect_ids.filtered(
                lambda d: d.product_id == line.product_id).mapped('qty')))
            line.total_qty = total
            line.defect_qty = defect
            line.good_qty = total - defect


class SnInjReportDefect(models.Model):
    _name = 'sn.inj.report.defect'
    _description = '报工不良明细'
    _order = 'report_id, id'

    report_id = fields.Many2one('sn.inj.report', string='报工单', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string='产品', required=True)
    defect_id = fields.Many2one('sn.inj.defect', string='缺陷', required=True)
    category = fields.Selection(related='defect_id.category', store=True, string='类别')
    qty = fields.Integer(string='数量', required=True)
    machine_id = fields.Many2one(related='report_id.machine_id', store=True, string='机台')
    mold_id = fields.Many2one(related='report_id.mold_id', store=True, string='模具')
    date = fields.Date(related='report_id.date', store=True, string='日期')
