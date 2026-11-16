from datetime import timedelta

from odoo import _, api, fields, models

MACHINE_BRANDS = [
    ('haitian', '海天'),
    ('yizumi', '伊之密'),
    ('chenhsong', '震雄'),
    ('lk', '力劲'),
    ('sumitomo', '住友重机'),
    ('engel', '恩格尔'),
    ('fanuc', '发那科'),
]

RUN_STATES = [
    ('running', '运行'),
    ('idle', '待机'),
    ('changeover', '换模'),
    ('fault', '故障停机'),
    ('wait_material', '待料'),
    ('planned_stop', '计划停机'),
]


class SnInjMachine(models.Model):
    """注塑机：委托继承设备台账 sn.wsd.device.equipment（点检/保养/维修/OEE 沿用设备模块），
    只扩展注塑专属的技术参数与运行状态；每台机自动对应一条「生产线」，用于复用异常管理。"""
    _name = 'sn.inj.machine'
    _description = '注塑机'
    _inherits = {'sn.wsd.device.equipment': 'equipment_id'}
    _inherit = ['mail.thread']
    _order = 'sequence, equipment_id'

    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='设备台账', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    brand = fields.Selection(MACHINE_BRANDS, string='品牌', tracking=True)
    drive_type = fields.Selection(
        [('hydraulic', '液压'), ('servo', '伺服节能'), ('electric', '全电动')],
        string='驱动方式', default='servo')
    tonnage = fields.Integer(string='吨位(T)', required=True, tracking=True)
    clamp_force_kn = fields.Float(string='锁模力(kN)')
    screw_diameter = fields.Float(string='螺杆直径(mm)')
    max_shot_weight = fields.Float(string='最大射胶量(g)')
    max_inject_pressure = fields.Float(string='最大注射压力(MPa)')
    tie_bar = fields.Char(string='拉杆内距(mm)')
    mold_thick_min = fields.Integer(string='最小容模厚度(mm)')
    mold_thick_max = fields.Integer(string='最大容模厚度(mm)')
    run_state = fields.Selection(RUN_STATES, string='机台状态', default='idle',
                                 required=True, tracking=True)
    state_since = fields.Datetime(string='状态起始')
    state_note = fields.Char(string='状态说明')
    current_mold_id = fields.Many2one('sn.inj.mold', string='当前模具', tracking=True, copy=False)
    current_plan_id = fields.Many2one('sn.inj.plan', string='当前工单', copy=False)
    production_line_id = fields.Many2one(
        'sn.mrp.production.line', string='对应产线', copy=False,
        help='注塑车间中与本机台一一对应的生产线，异常单等沿用产线维度。')
    workshop_id = fields.Many2one(related='production_line_id.workshop_id', string='车间', store=True)
    plan_ids = fields.One2many('sn.inj.plan', 'machine_id', string='排产计划')
    # 运行指标（读时计算，看板/列表使用）
    last_cycle = fields.Float(string='近 20 模平均周期(s)', compute='_compute_live')
    std_cycle = fields.Float(string='标准周期(s)', compute='_compute_live')
    cycle_dev_pct = fields.Float(string='周期偏差(%)', compute='_compute_live')
    oee_7d = fields.Float(string='近 7 天 OEE(%)', compute='_compute_live')
    today_good = fields.Integer(string='今日良品', compute='_compute_live')

    _sn_inj_machine_equipment_unique = models.Constraint(
        'unique(equipment_id)', '一台设备只能登记一次注塑机。')

    @api.depends('code', 'name', 'tonnage')
    def _compute_display_name(self):
        for machine in self:
            machine.display_name = '%s（%sT）' % (machine.code or '', machine.tonnage or 0)

    @api.model
    def _injection_workshop(self):
        workshop = self.env['sn.mrp.workshop'].search([('code', '=', 'WS-INJ')], limit=1)
        if not workshop:
            workshop = self.env['sn.mrp.workshop'].create({'name': '注塑车间', 'code': 'WS-INJ', 'sequence': 30})
        return workshop

    @api.model_create_multi
    def create(self, vals_list):
        machines = super().create(vals_list)
        workshop = self._injection_workshop()
        for machine in machines:
            if not machine.production_line_id:
                machine.production_line_id = self.env['sn.mrp.production.line'].create({
                    'name': '%s 注塑机' % machine.code,
                    'code': 'INJ-%s' % machine.code,
                    'workshop_id': workshop.id,
                    'x_line_type': 'auto',
                })
            if not machine.clamp_force_kn and machine.tonnage:
                machine.clamp_force_kn = round(machine.tonnage * 9.80665, 0)
        return machines

    def _compute_live(self):
        Shot = self.env['sn.inj.shot']
        Report = self.env['sn.inj.report']
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        for machine in self:
            shots = Shot.search([('machine_id', '=', machine.id)], order='shot_time desc', limit=20)
            machine.last_cycle = sum(shots.mapped('cycle_time')) / len(shots) if shots else 0.0
            plan = machine.current_plan_id
            std = plan.std_cycle if plan else (machine.current_mold_id.std_cycle or 0.0)
            machine.std_cycle = std
            machine.cycle_dev_pct = ((machine.last_cycle - std) / std * 100.0) if std and machine.last_cycle else 0.0
            reports = Report.search([('machine_id', '=', machine.id), ('state', '=', 'done'),
                                     ('report_time', '>=', now - timedelta(days=7))])
            planned = sum(reports.mapped('planned_minutes'))
            machine.oee_7d = (sum(r.oee * r.planned_minutes for r in reports) / planned) if planned else 0.0
            machine.today_good = int(sum(reports.filtered(lambda r: r.date == today).mapped('good_qty')))

    def _set_run_state(self, state, note=False, when=None):
        for machine in self:
            machine.write({'run_state': state, 'state_note': note or False,
                           'state_since': when or fields.Datetime.now()})
        return True

    def action_view_plans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('排产计划'),
            'res_model': 'sn.inj.plan', 'view_mode': 'list,form',
            'domain': [('machine_id', '=', self.id)],
            'context': {'default_machine_id': self.id},
        }

    def action_view_shots(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('逐模次参数'),
            'res_model': 'sn.inj.shot', 'view_mode': 'list,graph,pivot,form',
            'domain': [('machine_id', '=', self.id)],
        }

    def action_open_terminal(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/injection/terminal/%s' % self.code, 'target': 'new'}

    def action_generate_last_shift_oee(self):
        records = self.action_generate_oee()
        return {
            'type': 'ir.actions.act_window', 'name': _('OEE 记录'),
            'res_model': 'sn.wsd.device.oee.record', 'view_mode': 'list,form',
            'domain': [('equipment_id', 'in', self.equipment_id.ids)],
        }
