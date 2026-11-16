import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError

COOP_STATES = [('qualified', '合格'), ('trial', '试用'), ('suspended', '暂停')]
RATINGS = [('A', 'A 优秀'), ('B', 'B 良好'), ('C', 'C 一般'), ('D', 'D 不合格')]


class SnOutFactory(models.Model):
    """代工厂档案：同行注塑厂（整单代加工的承接方）。

    业务伙伴沿用 res.partner（作为供应商出现在采购单/对账单上），这里补充注塑代工
    选厂所需的资质、机台/吨位、擅长料种、产能、合作状态与绩效评级。
    """
    _name = 'sn.out.factory'
    _description = '代工厂档案'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    code = fields.Char(string='代工厂编号', required=True, copy=False, tracking=True)
    name = fields.Char(string='代工厂简称', required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='企业名称（供应商）', required=True, tracking=True,
                                 domain=[('is_company', '=', True)])
    city = fields.Char(string='所在地区')
    distance_km = fields.Integer(string='距本厂(km)')
    contact = fields.Char(string='业务联系人')
    phone = fields.Char(string='联系电话')
    coop_state = fields.Selection(COOP_STATES, string='合作状态', default='trial', required=True, tracking=True)
    coop_since = fields.Date(string='合作起始日')
    suspend_reason = fields.Char(string='暂停原因', tracking=True)
    rating = fields.Selection(RATINGS, string='综合评级', tracking=True)
    rating_score = fields.Float(string='综合得分', digits=(5, 1), tracking=True)
    rating_period = fields.Char(string='评级期间')
    tonnage_min = fields.Integer(string='可做吨位下限(T)')
    tonnage_max = fields.Integer(string='可做吨位上限(T)')
    tonnage_text = fields.Char(string='吨位范围', compute='_compute_tonnage_text')
    machine_ids = fields.One2many('sn.out.factory.machine', 'factory_id', string='机台清单')
    machine_count = fields.Integer(string='注塑机(台)', compute='_compute_machine_stats', store=True)
    grade_ids = fields.Many2many('sn.inj.material.grade', string='擅长料种')
    grade_text = fields.Char(string='料种清单', compute='_compute_grade_text')
    shift_mode = fields.Selection([('2x12', '两班 12h'), ('3x8', '三班 8h'), ('1x10', '单班 10h')],
                                  string='班制', default='2x12')
    capacity_shots_day = fields.Integer(string='可承接产能(模次/日)')
    capacity_pcs_day = fields.Integer(string='可承接产能(件/日)')
    capability = fields.Text(string='工艺能力')
    cert_ids = fields.One2many('sn.out.factory.cert', 'factory_id', string='资质证书')
    cert_text = fields.Char(string='资质', compute='_compute_cert_text')
    location_id = fields.Many2one('stock.location', string='委外库位', readonly=True, copy=False,
                                  help='发给该代工厂的物料、借出的模具都挂在此库位，账面可见。')
    api_token = fields.Char(string='进度接口密钥', copy=False, groups='mrp.group_mrp_manager',
                            default=lambda self: secrets.token_hex(8))
    order_ids = fields.One2many('sn.out.order', 'factory_id', string='代工单')
    order_count = fields.Integer(string='代工单数', compute='_compute_counts')
    open_order_count = fields.Integer(string='在制代工单', compute='_compute_counts')
    loan_count = fields.Integer(string='在借模具', compute='_compute_counts')
    kpi_ids = fields.One2many('sn.out.kpi', 'factory_id', string='绩效记录')
    last_ontime_rate = fields.Float(string='准交率(%)', compute='_compute_last_kpi')
    last_pass_rate = fields.Float(string='合格率(%)', compute='_compute_last_kpi')
    last_excess_rate = fields.Float(string='超耗率(%)', compute='_compute_last_kpi', digits=(5, 2))
    note = fields.Text(string='备注')
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint('unique(code)', '代工厂编号不能重复。')

    @api.depends('machine_ids.qty')
    def _compute_machine_stats(self):
        for rec in self:
            rec.machine_count = sum(rec.machine_ids.mapped('qty'))

    @api.depends('tonnage_min', 'tonnage_max')
    def _compute_tonnage_text(self):
        for rec in self:
            if rec.tonnage_min or rec.tonnage_max:
                rec.tonnage_text = '%s–%sT' % (rec.tonnage_min or 0, rec.tonnage_max or 0)
            else:
                rec.tonnage_text = False

    @api.depends('grade_ids')
    def _compute_grade_text(self):
        for rec in self:
            rec.grade_text = '、'.join(rec.grade_ids.mapped('code'))

    @api.depends('cert_ids.name', 'cert_ids.state')
    def _compute_cert_text(self):
        for rec in self:
            rec.cert_text = '、'.join(rec.cert_ids.filtered(lambda c: c.state != 'expired').mapped('name'))

    def _compute_counts(self):
        Loan = self.env['sn.out.mold.loan']
        for rec in self:
            rec.order_count = len(rec.order_ids)
            rec.open_order_count = len(rec.order_ids.filtered(
                lambda o: o.state in ('released', 'producing', 'partial')))
            rec.loan_count = Loan.search_count([('factory_id', '=', rec.id), ('state', '=', 'loaned')])

    def _compute_last_kpi(self):
        for rec in self:
            kpi = rec.kpi_ids.sorted('date_to', reverse=True)[:1]
            rec.last_ontime_rate = kpi.ontime_rate
            rec.last_pass_rate = kpi.pass_rate
            rec.last_excess_rate = kpi.excess_rate

    @api.model
    def _subcon_parent_location(self):
        wh = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        parent = self.env['stock.location'].search(
            [('name', '=', '委外仓'), ('location_id', '=', wh.view_location_id.id)], limit=1)
        if not parent:
            parent = self.env['stock.location'].create({
                'name': '委外仓', 'usage': 'view', 'location_id': wh.view_location_id.id})
        return parent

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.location_id:
                rec.location_id = self.env['stock.location'].create({
                    'name': rec.name, 'usage': 'internal',
                    'location_id': self._subcon_parent_location().id}).id
            if not rec.partner_id.supplier_rank:
                rec.partner_id.supplier_rank = 1
        return records

    def _check_awardable(self):
        for rec in self:
            if rec.coop_state == 'suspended':
                raise UserError(_('代工厂「%(f)s」合作状态为「暂停」（%(r)s），不能定点或下达代工单。',
                                  f=rec.name, r=rec.suspend_reason or _('未注明原因')))
        return True

    def action_set_qualified(self):
        self.write({'coop_state': 'qualified', 'suspend_reason': False})
        return True

    def action_set_trial(self):
        self.write({'coop_state': 'trial', 'suspend_reason': False})
        return True

    def action_suspend(self):
        for rec in self:
            rec.write({'coop_state': 'suspended',
                       'suspend_reason': rec.suspend_reason or _('手工暂停')})
        return True

    def action_view_orders(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('代工单'), 'res_model': 'sn.out.order',
                'view_mode': 'list,form', 'domain': [('factory_id', '=', self.id)],
                'context': {'default_factory_id': self.id}}

    def action_view_loans(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('模具外借'), 'res_model': 'sn.out.mold.loan',
                'view_mode': 'list,form', 'domain': [('factory_id', '=', self.id)]}

    def action_view_kpi(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('代工厂绩效'), 'res_model': 'sn.out.kpi',
                'view_mode': 'list,graph,pivot', 'domain': [('factory_id', '=', self.id)]}


class SnOutFactoryMachine(models.Model):
    _name = 'sn.out.factory.machine'
    _description = '代工厂机台清单'
    _order = 'factory_id, tonnage, id'

    factory_id = fields.Many2one('sn.out.factory', required=True, ondelete='cascade', index=True)
    brand = fields.Char(string='品牌', required=True)
    model = fields.Char(string='型号')
    tonnage = fields.Integer(string='吨位(T)', required=True)
    qty = fields.Integer(string='台数', default=1, required=True)
    year = fields.Char(string='购置年份')
    note = fields.Char(string='配置说明')


class SnOutFactoryCert(models.Model):
    _name = 'sn.out.factory.cert'
    _description = '代工厂资质证书'
    _order = 'factory_id, date_expire, id'

    factory_id = fields.Many2one('sn.out.factory', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='资质名称', required=True)
    number = fields.Char(string='证书编号')
    issuer = fields.Char(string='发证机构')
    date_expire = fields.Date(string='有效期至')
    state = fields.Selection([('valid', '有效'), ('expiring', '临期'), ('expired', '已过期')],
                             string='状态', compute='_compute_state')

    @api.depends('date_expire')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.date_expire:
                rec.state = 'valid'
            elif rec.date_expire < today:
                rec.state = 'expired'
            elif (rec.date_expire - today).days <= 60:
                rec.state = 'expiring'
            else:
                rec.state = 'valid'
