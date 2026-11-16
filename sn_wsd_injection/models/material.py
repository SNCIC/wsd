from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

RESIN_FAMILY = [
    ('pc', 'PC'),
    ('pc_abs', 'PC/ABS'),
    ('pa66_gf', 'PA66+GF'),
    ('pa6', 'PA6'),
    ('abs', 'ABS'),
    ('pp', 'PP'),
    ('pbt', 'PBT'),
    ('pom', 'POM'),
]


class SnInjMaterialGrade(models.Model):
    """料种（树脂牌号）：烘料标准 + 水口料回用上限。"""
    _name = 'sn.inj.material.grade'
    _description = '注塑料种'
    _order = 'sequence, code, id'

    sequence = fields.Integer(default=10)
    code = fields.Char(string='料种编码', required=True)
    name = fields.Char(string='料种', required=True)
    family = fields.Selection(RESIN_FAMILY, string='树脂类别', required=True)
    brand_grade = fields.Char(string='供应商牌号')
    product_id = fields.Many2one('product.product', string='原料物料')
    need_drying = fields.Boolean(string='需要烘干', default=True)
    dry_temp = fields.Float(string='标准烘干温度(℃)')
    dry_temp_tol = fields.Float(string='温度允差(±℃)', default=5.0)
    dry_hours = fields.Float(string='最短烘干时长(h)')
    dew_point_max = fields.Float(string='露点上限(℃)', default=-30.0)
    moisture_max = fields.Float(string='含水率上限(%)', digits=(6, 3))
    hold_hours = fields.Float(
        string='烘后可用时长(h)', default=4.0,
        help='烘干结束后在料斗/保温桶中可直接使用的时间窗口，超过需重新烘干。')
    regrind_max_pct = fields.Float(string='水口料回用上限(%)', default=20.0)
    regrind_control = fields.Selection(
        [('block', '超限禁止投料'), ('warn', '超限告警放行')],
        string='超限控制方式', default='block', required=True)
    note = fields.Text(string='工艺说明')
    active = fields.Boolean(default=True)

    _sn_inj_grade_code_unique = models.Constraint(
        'unique(code)', '料种编码必须唯一。')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for grade in self:
            grade.display_name = grade.name or grade.code


class SnInjDryer(models.Model):
    """干燥机：委托继承设备台账（sn.wsd.device.equipment），只扩展干燥参数。"""
    _name = 'sn.inj.dryer'
    _description = '注塑干燥机'
    _inherits = {'sn.wsd.device.equipment': 'equipment_id'}
    _order = 'equipment_id'

    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='设备台账', required=True,
        ondelete='cascade', index=True)
    dryer_type = fields.Selection(
        [('dehumid', '除湿干燥机'), ('hot_air', '热风干燥机'), ('central', '中央干燥系统')],
        string='干燥机类型', default='dehumid', required=True)
    capacity_kg = fields.Float(string='料桶容量(kg)')
    max_temp = fields.Float(string='最高温度(℃)', default=180)
    machine_ids = fields.Many2many('sn.inj.machine', string='供料机台')
    drying_ids = fields.One2many('sn.inj.drying', 'dryer_id', string='烘干记录')
    current_drying_id = fields.Many2one(
        'sn.inj.drying', string='当前批次', compute='_compute_current')

    def _compute_current(self):
        for dryer in self:
            dryer.current_drying_id = dryer.drying_ids.filtered(
                lambda d: d.state in ('drying', 'wait_test', 'ok'))[:1]

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for dryer in self:
            dryer.display_name = dryer.code or dryer.name


class SnInjDrying(models.Model):
    """原料烘干记录：上料批次 → 烘干 → 含水率检测 → 可用窗口（超时重烘）。"""
    _name = 'sn.inj.drying'
    _description = '原料烘干记录'
    _inherit = ['mail.thread']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='烘干单号', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    dryer_id = fields.Many2one('sn.inj.dryer', string='干燥机', required=True, tracking=True)
    grade_id = fields.Many2one('sn.inj.material.grade', string='料种', required=True, tracking=True)
    lot_no = fields.Char(string='原料批次', required=True)
    qty_kg = fields.Float(string='上料量(kg)')
    machine_id = fields.Many2one('sn.inj.machine', string='供料机台')
    operator_id = fields.Many2one('hr.employee', string='上料人')
    std_temp = fields.Float(related='grade_id.dry_temp', string='标准温度(℃)')
    std_hours = fields.Float(related='grade_id.dry_hours', string='标准时长(h)')
    moisture_max = fields.Float(related='grade_id.moisture_max', string='含水率上限(%)')
    set_temp = fields.Float(string='设定温度(℃)')
    actual_temp = fields.Float(string='实测温度(℃)')
    dew_point = fields.Float(string='露点(℃)')
    temp_abnormal = fields.Boolean(string='温度异常', compute='_compute_temp_abnormal', store=True)
    date_start = fields.Datetime(string='开始烘干', required=True, default=fields.Datetime.now)
    planned_end = fields.Datetime(string='最早出料', compute='_compute_planned_end', store=True)
    date_end = fields.Datetime(string='结束烘干')
    dry_hours_actual = fields.Float(string='实际烘干(h)', compute='_compute_hours', store=True)
    moisture = fields.Float(string='含水率(%)', digits=(6, 3), tracking=True)
    test_time = fields.Datetime(string='检测时间')
    usable_until = fields.Datetime(string='可用截止', compute='_compute_usable_until', store=True)
    window_text = fields.Char(string='可用窗口', compute='_compute_window_text')
    state = fields.Selection(
        [('drying', '烘干中'), ('wait_test', '待检测'), ('ok', '合格可用'),
         ('ng', '含水超标'), ('expired', '超时需重烘'), ('used', '已用完')],
        string='状态', default='drying', required=True, tracking=True)
    redry_of_id = fields.Many2one('sn.inj.drying', string='重烘来源')
    note = fields.Char(string='备注')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.inj.drying') or _('New')
            if not vals.get('set_temp') and vals.get('grade_id'):
                vals['set_temp'] = self.env['sn.inj.material.grade'].browse(vals['grade_id']).dry_temp
        return super().create(vals_list)

    @api.depends('date_start', 'grade_id.dry_hours')
    def _compute_planned_end(self):
        for rec in self:
            rec.planned_end = rec.date_start and rec.date_start + timedelta(hours=rec.grade_id.dry_hours or 0)

    @api.depends('date_start', 'date_end')
    def _compute_hours(self):
        for rec in self:
            rec.dry_hours_actual = (
                (rec.date_end - rec.date_start).total_seconds() / 3600.0
                if rec.date_end and rec.date_start else 0.0)

    @api.depends('actual_temp', 'grade_id.dry_temp', 'grade_id.dry_temp_tol')
    def _compute_temp_abnormal(self):
        for rec in self:
            rec.temp_abnormal = bool(
                rec.actual_temp and rec.grade_id.dry_temp
                and abs(rec.actual_temp - rec.grade_id.dry_temp) > (rec.grade_id.dry_temp_tol or 0))

    @api.depends('date_end', 'planned_end', 'grade_id.hold_hours')
    def _compute_usable_until(self):
        for rec in self:
            end = rec.date_end or rec.planned_end
            rec.usable_until = end and end + timedelta(hours=rec.grade_id.hold_hours or 0)

    def _compute_window_text(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state == 'ok' and rec.usable_until:
                left = (rec.usable_until - now).total_seconds() / 3600.0
                rec.window_text = _('可用，剩 %.1f 小时', left) if left > 0 else _('已超时')
            elif rec.state == 'drying' and rec.planned_end:
                left = (rec.planned_end - now).total_seconds() / 3600.0
                rec.window_text = _('距出料 %.1f 小时', left) if left > 0 else _('可出料')
            elif rec.state == 'expired':
                rec.window_text = _('需重新烘干')
            else:
                rec.window_text = ''

    def action_finish(self, when=None):
        when = when or fields.Datetime.now()
        for rec in self:
            if rec.state != 'drying':
                raise UserError(_('只有烘干中的批次可以结束烘干。'))
            if rec.planned_end and when < rec.planned_end:
                raise UserError(_('烘干时长不足 %(h)s 小时（%(grade)s 标准），不允许出料。',
                                  h=rec.grade_id.dry_hours, grade=rec.grade_id.name))
            rec.write({'date_end': when, 'state': 'wait_test'})
        return True

    def action_test(self, moisture, when=None):
        when = when or fields.Datetime.now()
        for rec in self:
            if rec.state not in ('wait_test', 'ng'):
                raise UserError(_('当前状态不能录入含水率。'))
            ok = moisture <= (rec.grade_id.moisture_max or 0) + 1e-9
            rec.write({'moisture': moisture, 'test_time': when, 'state': 'ok' if ok else 'ng'})
            if not ok:
                rec.message_post(body=_('含水率 %(m)s%% 超过上限 %(mx)s%%，需继续烘干。',
                                        m=moisture, mx=rec.grade_id.moisture_max))
        return True

    def action_mark_used(self):
        self.filtered(lambda r: r.state == 'ok').write({'state': 'used'})
        return True

    def action_redry(self):
        new = self.env['sn.inj.drying']
        for rec in self:
            if rec.state not in ('expired', 'ng'):
                raise UserError(_('只有超时或含水超标的批次需要重新烘干。'))
            new |= rec.copy({'redry_of_id': rec.id, 'date_start': fields.Datetime.now(),
                             'date_end': False, 'moisture': 0, 'test_time': False,
                             'state': 'drying', 'note': _('重烘：%s', rec.name)})
            if rec.state == 'expired':
                rec.state = 'used'
        if len(new) == 1:
            return {'type': 'ir.actions.act_window', 'res_model': 'sn.inj.drying',
                    'res_id': new.id, 'view_mode': 'form'}
        return True

    @api.model
    def _cron_check_window(self):
        """合格批次超过可用窗口 → 标记“超时需重烘”并提醒。"""
        expired = self.search([('state', '=', 'ok'), ('usable_until', '<', fields.Datetime.now())])
        for rec in expired:
            rec.state = 'expired'
            rec.message_post(body=_('已超过烘后可用时间窗口（%s 小时），请重新烘干后再投料。',
                                    rec.grade_id.hold_hours))
        return True
