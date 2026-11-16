from odoo import _, api, fields, models
from odoo.exceptions import UserError

MOVE_TYPES = [('generate', '产生（报工自动）'), ('crush', '粉碎入库'), ('reuse', '回用投料'), ('scrap', '报废外售')]


class SnInjRegrind(models.Model):
    """水口料台账：报工按「模次 × 水口重」自动记产生量 → 粉碎入库 → 投料回用 / 报废。"""
    _name = 'sn.inj.regrind'
    _description = '水口料台账'
    _order = 'move_time desc, id desc'

    name = fields.Char(string='单号', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    move_type = fields.Selection(MOVE_TYPES, string='业务类型', required=True)
    move_time = fields.Datetime(string='发生时间', required=True, default=fields.Datetime.now)
    move_date = fields.Date(string='日期', compute='_compute_date', store=True)
    grade_id = fields.Many2one('sn.inj.material.grade', string='料种', required=True, index=True)
    color_no = fields.Char(string='颜色')
    machine_id = fields.Many2one('sn.inj.machine', string='机台')
    report_id = fields.Many2one('sn.inj.report', string='来源报工', ondelete='cascade')
    mix_id = fields.Many2one('sn.inj.mix', string='投料单', ondelete='cascade')
    lot_no = fields.Char(string='碎料批次')
    qty_kg = fields.Float(string='重量(kg)', digits=(10, 2))
    pending_delta = fields.Float(string='待粉碎变动(kg)', compute='_compute_delta', store=True)
    stock_delta = fields.Float(string='碎料库存变动(kg)', compute='_compute_delta', store=True)
    operator_id = fields.Many2one('hr.employee', string='经办人')
    note = fields.Char(string='备注')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.regrind') or _('New')
        return super().create(vals_list)

    @api.depends('move_time')
    def _compute_date(self):
        for rec in self:
            rec.move_date = rec.move_time and fields.Datetime.context_timestamp(rec, rec.move_time).date()

    @api.depends('move_type', 'qty_kg')
    def _compute_delta(self):
        for rec in self:
            sign = {'generate': (1, 0), 'crush': (-1, 1), 'reuse': (0, -1), 'scrap': (0, -1)}[rec.move_type]
            rec.pending_delta = sign[0] * rec.qty_kg
            rec.stock_delta = sign[1] * rec.qty_kg

    @api.model
    def _stock(self, grade):
        rows = self._read_group([('grade_id', '=', grade.id)], aggregates=['stock_delta:sum', 'pending_delta:sum'])
        stock, pending = rows[0] if rows else (0.0, 0.0)
        return stock or 0.0, pending or 0.0


class SnInjMix(models.Model):
    """投料/配料单：新料 + 水口料（+ 色母）。
    闸门 1：需烘干料种必须引用「合格可用」且在可用窗口内的烘干批次（时长/含水率/窗口任一不达标拦截）；
    闸门 2：水口料掺比 ≤ 上限（产品上限优先，其次工艺卡、料种），超限按料种控制方式禁止或告警。"""
    _name = 'sn.inj.mix'
    _description = '投料配料单'
    _inherit = ['mail.thread']
    _order = 'mix_time desc, id desc'

    name = fields.Char(string='投料单号', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    mix_time = fields.Datetime(string='投料时间', required=True, default=fields.Datetime.now)
    machine_id = fields.Many2one('sn.inj.machine', string='机台', required=True)
    plan_id = fields.Many2one('sn.inj.plan', string='排产计划')
    product_id = fields.Many2one(related='plan_id.product_id', string='产品')
    grade_id = fields.Many2one('sn.inj.material.grade', string='料种', required=True)
    drying_id = fields.Many2one('sn.inj.drying', string='烘干批次',
                                domain="[('grade_id', '=', grade_id), ('state', '=', 'ok')]")
    color_batch_id = fields.Many2one('sn.inj.color.batch', string='配色批次')
    virgin_kg = fields.Float(string='新料(kg)')
    regrind_kg = fields.Float(string='水口料(kg)')
    regrind_lot = fields.Char(string='碎料批次')
    total_kg = fields.Float(string='合计(kg)', compute='_compute_ratio', store=True)
    regrind_pct = fields.Float(string='水口料掺比(%)', compute='_compute_ratio', store=True)
    limit_pct = fields.Float(string='允许上限(%)', compute='_compute_ratio', store=True)
    over_limit = fields.Boolean(string='超限', compute='_compute_ratio', store=True)
    state = fields.Selection([('draft', '草稿'), ('done', '已投料'), ('blocked', '已拦截')],
                             string='状态', default='draft', tracking=True)
    block_reason = fields.Char(string='拦截/告警原因')
    operator_id = fields.Many2one('hr.employee', string='投料人')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.mix') or _('New')
        return super().create(vals_list)

    @api.depends('virgin_kg', 'regrind_kg', 'grade_id.regrind_max_pct', 'plan_id.product_id', 'plan_id.card_id')
    def _compute_ratio(self):
        for rec in self:
            rec.total_kg = rec.virgin_kg + rec.regrind_kg
            rec.regrind_pct = round(rec.regrind_kg * 100.0 / rec.total_kg, 2) if rec.total_kg else 0.0
            limit = rec.plan_id.product_id.product_tmpl_id.x_inj_regrind_max_pct if rec.plan_id else 0.0
            limit = limit or rec.plan_id.card_id.regrind_max_pct or rec.grade_id.regrind_max_pct
            rec.limit_pct = limit
            rec.over_limit = bool(rec.regrind_kg and rec.regrind_pct > limit + 1e-9)

    def _check_drying(self):
        self.ensure_one()
        grade = self.grade_id
        if not grade.need_drying:
            return
        d = self.drying_id
        if not d:
            raise UserError(_('料种 %s 需要烘干，请选择合格的烘干批次后再投料。', grade.name))
        when = self.mix_time
        if d.state != 'ok':
            raise UserError(_('烘干批次 %(d)s 状态为「%(s)s」，不能投料。', d=d.name,
                              s=dict(d._fields['state'].selection).get(d.state)))
        if d.dry_hours_actual + 1e-6 < (grade.dry_hours or 0):
            raise UserError(_('烘干批次 %(d)s 实际烘干 %(a).1f 小时，未达标准 %(s)s 小时。',
                              d=d.name, a=d.dry_hours_actual, s=grade.dry_hours))
        if grade.moisture_max and d.moisture > grade.moisture_max:
            raise UserError(_('烘干批次 %(d)s 含水率 %(m)s%% 超过上限 %(x)s%%。', d=d.name, m=d.moisture,
                              x=grade.moisture_max))
        if d.usable_until and when > d.usable_until:
            raise UserError(_('烘干批次 %(d)s 已超出可用窗口（截止 %(t)s），请重新烘干。', d=d.name,
                              t=fields.Datetime.context_timestamp(self, d.usable_until).strftime('%m-%d %H:%M')))

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('只有草稿可以确认投料。'))
            rec._check_drying()
            if rec.regrind_kg:
                stock, _pending = self.env['sn.inj.regrind']._stock(rec.grade_id)
                if rec.regrind_kg > stock + 1e-6:
                    raise UserError(_('%(g)s 碎料库存仅 %(s).1f kg，不足 %(q)s kg。', g=rec.grade_id.name, s=stock,
                                      q=rec.regrind_kg))
            if rec.over_limit:
                msg = _('水口料掺比 %(r)s%% 超过上限 %(l)s%%', r=rec.regrind_pct, l=rec.limit_pct)
                if rec.grade_id.regrind_control == 'block':
                    raise UserError(msg + _('，禁止投料。'))
                rec.block_reason = msg + _('（告警放行）')
                rec.message_post(body=rec.block_reason)
            if rec.regrind_kg:
                self.env['sn.inj.regrind'].create({
                    'move_type': 'reuse', 'move_time': rec.mix_time, 'grade_id': rec.grade_id.id,
                    'machine_id': rec.machine_id.id, 'mix_id': rec.id, 'lot_no': rec.regrind_lot,
                    'qty_kg': rec.regrind_kg, 'operator_id': rec.operator_id.id,
                })
            rec.state = 'done'
        return True


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_inj_regrind_max_pct = fields.Float(
        string='水口料回用上限(%)',
        help='注塑件的水口料掺比上限；0 表示按工艺卡/料种。外观件、透明件通常更严。')
