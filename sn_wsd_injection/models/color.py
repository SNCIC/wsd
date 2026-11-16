from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

COMPONENT_KINDS = [('base', '基料'), ('masterbatch', '色母'), ('additive', '添加剂'), ('regrind', '水口料')]


class SnInjColorRecipe(models.Model):
    """配色配方：基料 + 色母/添加剂（+ 允许的水口料）比例，色号与色差标准。"""
    _name = 'sn.inj.color.recipe'
    _description = '配色配方'
    _inherit = ['mail.thread']
    _order = 'code'

    code = fields.Char(string='配方编号', required=True)
    name = fields.Char(string='配方名称', required=True)
    color_no = fields.Char(string='色号')
    color_name = fields.Char(string='颜色')
    color_hex = fields.Char(string='色板')
    grade_id = fields.Many2one('sn.inj.material.grade', string='基料料种', required=True)
    product_ids = fields.Many2many('product.product', string='适用产品')
    line_ids = fields.One2many('sn.inj.color.recipe.line', 'recipe_id', string='配方组成', copy=True)
    total_pct = fields.Float(string='合计(%)', compute='_compute_pct', store=True)
    masterbatch_pct = fields.Float(string='色母比例(%)', compute='_compute_pct', store=True)
    regrind_pct = fields.Float(string='水口料比例(%)', compute='_compute_pct', store=True)
    let_down = fields.Char(string='稀释比', compute='_compute_pct', store=True)
    delta_e_max = fields.Float(string='色差 ΔE 上限', default=1.0)
    mix_minutes = fields.Integer(string='混料时间(分钟)', default=10)
    version = fields.Char(string='版本', default='A0')
    state = fields.Selection([('draft', '草稿'), ('active', '生效'), ('obsolete', '作废')],
                             string='状态', default='draft', tracking=True)
    batch_ids = fields.One2many('sn.inj.color.batch', 'recipe_id', string='配色批次')
    batch_count = fields.Integer(compute='_compute_batch_count')
    note = fields.Text(string='说明')

    _sn_inj_recipe_code_unique = models.Constraint('unique(code)', '配方编号必须唯一。')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s %s' % (rec.code, rec.name)

    @api.depends('line_ids.ratio_pct', 'line_ids.kind')
    def _compute_pct(self):
        for rec in self:
            rec.total_pct = round(sum(rec.line_ids.mapped('ratio_pct')), 3)
            mb = sum(rec.line_ids.filtered(lambda l: l.kind == 'masterbatch').mapped('ratio_pct'))
            rec.masterbatch_pct = mb
            rec.regrind_pct = sum(rec.line_ids.filtered(lambda l: l.kind == 'regrind').mapped('ratio_pct'))
            rec.let_down = '1:%d' % round((100 - mb) / mb) if mb else ''

    def _compute_batch_count(self):
        for rec in self:
            rec.batch_count = len(rec.batch_ids)

    @api.constrains('state', 'line_ids', 'regrind_pct')
    def _check_total(self):
        for rec in self.filtered(lambda r: r.state == 'active'):
            if abs(rec.total_pct - 100) > 0.001:
                raise ValidationError(_('配方 %(c)s 各组分合计为 %(t)s%%，必须为 100%%。', c=rec.code, t=rec.total_pct))
            limit = rec.grade_id.regrind_max_pct
            if limit and rec.regrind_pct > limit:
                raise ValidationError(_('配方水口料比例 %(r)s%% 超过料种上限 %(l)s%%。', r=rec.regrind_pct, l=limit))

    def action_activate(self):
        self.write({'state': 'active'})
        return True

    def action_obsolete(self):
        self.write({'state': 'obsolete'})
        return True


class SnInjColorRecipeLine(models.Model):
    _name = 'sn.inj.color.recipe.line'
    _description = '配方组成'
    _order = 'recipe_id, sequence, id'

    recipe_id = fields.Many2one('sn.inj.color.recipe', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection(COMPONENT_KINDS, string='类别', required=True, default='base')
    material = fields.Char(string='物料/牌号', required=True)
    supplier = fields.Char(string='供应商')
    ratio_pct = fields.Float(string='比例(%)', digits=(6, 3))
    note = fields.Char(string='说明')


class SnInjColorBatch(models.Model):
    """配色/混料批次记录：按配方比例计算色母用量，记录批号与色差检测。"""
    _name = 'sn.inj.color.batch'
    _description = '配色批次'
    _order = 'mix_time desc, id desc'

    name = fields.Char(string='配色批号', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    recipe_id = fields.Many2one('sn.inj.color.recipe', string='配方', required=True, index=True)
    color_no = fields.Char(related='recipe_id.color_no', string='色号')
    machine_id = fields.Many2one('sn.inj.machine', string='机台')
    mix_time = fields.Datetime(string='配色时间', default=fields.Datetime.now)
    total_kg = fields.Float(string='混料总量(kg)')
    base_kg = fields.Float(string='基料(kg)', compute='_compute_qty', store=True)
    masterbatch_kg = fields.Float(string='色母(kg)', compute='_compute_qty', store=True, digits=(10, 3))
    base_lot = fields.Char(string='基料批次')
    masterbatch_lot = fields.Char(string='色母批次')
    operator_id = fields.Many2one('hr.employee', string='配色员')
    delta_e = fields.Float(string='色差 ΔE', digits=(6, 2))
    result = fields.Selection([('pass', '合格'), ('fail', '色差超标'), ('pending', '待检')],
                              string='判定', compute='_compute_result', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.color.batch') or _('New')
        return super().create(vals_list)

    @api.depends('total_kg', 'recipe_id.masterbatch_pct', 'recipe_id.regrind_pct')
    def _compute_qty(self):
        for rec in self:
            rec.masterbatch_kg = round(rec.total_kg * rec.recipe_id.masterbatch_pct / 100.0, 3)
            rec.base_kg = round(rec.total_kg - rec.masterbatch_kg, 3)

    @api.depends('delta_e', 'recipe_id.delta_e_max')
    def _compute_result(self):
        for rec in self:
            if not rec.delta_e:
                rec.result = 'pending'
            else:
                rec.result = 'pass' if rec.delta_e <= rec.recipe_id.delta_e_max else 'fail'
