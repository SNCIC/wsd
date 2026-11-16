import math
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .process_card import PARAM_NAMES, PARAM_UNITS
from .shift import SHIFTS, shift_of

# 逐模次字段 → 工艺卡参数代码
SHOT_PARAM_MAP = {
    'cycle_time': 'cycle',
    'inject_time': 'inj_time',
    'peak_pressure': 'peak_p',
    'hold_pressure': 'hold_p1',
    'vp_position': 'vp_pos',
    'melt_temp': 'melt_t',
    'mold_temp': 'mold_t_fixed',
    'cushion': 'cushion',
    'metering_time': 'meter_time',
}
# Xbar-R 控制图系数（子组容量 n → A2, D3, D4, d2）
XBAR_R_CONST = {
    2: (1.880, 0.0, 3.267, 1.128), 3: (1.023, 0.0, 2.574, 1.693), 4: (0.729, 0.0, 2.282, 2.059),
    5: (0.577, 0.0, 2.114, 2.326), 6: (0.483, 0.0, 2.004, 2.534),
}
EXCEPTION_CATEGORY_CODE = 'INJ-PARAM'


class SnInjShot(models.Model):
    """逐模次工艺参数：设备接口 /api/injection/shot 上传或导入，
    入库即按生效工艺卡判断超限，连续超限自动生成异常单（复用 MES 异常管理）。"""
    _name = 'sn.inj.shot'
    _description = '逐模次工艺参数'
    _order = 'shot_time desc, id desc'
    _rec_name = 'shot_no'

    machine_id = fields.Many2one('sn.inj.machine', string='机台', required=True, index=True)
    mold_id = fields.Many2one('sn.inj.mold', string='模具', required=True, index=True)
    plan_id = fields.Many2one('sn.inj.plan', string='排产计划', index=True)
    product_id = fields.Many2one('product.product', string='产品')
    card_id = fields.Many2one('sn.inj.process.card', string='工艺卡')
    shot_no = fields.Integer(string='模次号', aggregator=None)
    shot_time = fields.Datetime(string='采集时间', required=True, default=fields.Datetime.now, index=True)
    shot_date = fields.Date(string='班次日期', compute='_compute_shot_date', store=True, index=True)
    shift = fields.Selection(SHIFTS, string='班次', compute='_compute_shot_date', store=True)
    cycle_time = fields.Float(string='成型周期(s)', digits=(8, 2), aggregator='avg')
    inject_time = fields.Float(string='注射时间(s)', digits=(8, 2), aggregator='avg')
    peak_pressure = fields.Float(string='射出峰压(MPa)', digits=(8, 1), aggregator='avg')
    hold_pressure = fields.Float(string='保压压力(MPa)', digits=(8, 1), aggregator='avg')
    vp_position = fields.Float(string='V/P 位置(mm)', digits=(8, 2), aggregator='avg')
    melt_temp = fields.Float(string='料温(℃)', digits=(8, 1), aggregator='avg')
    mold_temp = fields.Float(string='模温(℃)', digits=(8, 1), aggregator='avg')
    cushion = fields.Float(string='垫料量(mm)', digits=(8, 2), aggregator='avg')
    metering_time = fields.Float(string='计量时间(s)', digits=(8, 2), aggregator='avg')
    is_out = fields.Boolean(string='超限', index=True)
    out_count = fields.Integer(string='超限项数', aggregator='sum')
    out_items = fields.Char(string='超限说明')
    source = fields.Selection([('api', '设备接口'), ('import', '批量导入'), ('manual', '手工')],
                              string='来源', default='api')
    exception_id = fields.Many2one('sn.wsd.exception.ticket', string='异常单', index=True)

    @api.depends('shot_time')
    def _compute_shot_date(self):
        for shot in self:
            if shot.shot_time:
                shot.shot_date, shot.shift = shift_of(self.env, shot.shot_time)
            else:
                shot.shot_date, shot.shift = False, False

    @api.model_create_multi
    def create(self, vals_list):
        Card = self.env['sn.inj.process.card']
        Plan = self.env['sn.inj.plan']
        card_cache = {}
        for vals in vals_list:
            if not vals.get('plan_id'):
                plan = Plan.search([('machine_id', '=', vals['machine_id']), ('mold_id', '=', vals['mold_id']),
                                    ('state', 'in', ('running', 'confirmed', 'done')),
                                    ('date_start', '<=', vals.get('shot_time') or fields.Datetime.now())],
                                   order='date_start desc', limit=1)
                vals['plan_id'] = plan.id
            plan = Plan.browse(vals.get('plan_id'))
            if not vals.get('product_id'):
                vals['product_id'] = (plan.product_id or self.env['sn.inj.mold'].browse(
                    vals['mold_id']).product_line_ids[:1].product_id).id
            if not vals.get('card_id'):
                key = (vals.get('product_id'), vals['mold_id'])
                if key not in card_cache:
                    card_cache[key] = (plan.card_id if plan and plan.card_id else Card._active_for(
                        self.env['product.product'].browse(vals.get('product_id')),
                        self.env['sn.inj.mold'].browse(vals['mold_id'])))
                vals['card_id'] = card_cache[key].id
            card = Card.browse(vals.get('card_id'))
            vals.update(self._judge(vals, card._limits() if card else {}))
        shots = super().create(vals_list)
        if not self.env.context.get('inj_skip_exception'):
            shots.filtered('is_out')._raise_exceptions()
        return shots

    @api.model
    def _judge(self, vals, limits):
        items = []
        for field_name, code in SHOT_PARAM_MAP.items():
            if code not in limits or vals.get(field_name) in (None, False):
                continue
            _std, low, up = limits[code]
            value = vals[field_name]
            if value < low - 1e-9:
                items.append(_('%(n)s %(v)s%(u)s < 下限 %(l)s', n=PARAM_NAMES[code], v=round(value, 2),
                               u=PARAM_UNITS[code], l=low))
            elif value > up + 1e-9:
                items.append(_('%(n)s %(v)s%(u)s > 上限 %(l)s', n=PARAM_NAMES[code], v=round(value, 2),
                               u=PARAM_UNITS[code], l=up))
        return {'is_out': bool(items), 'out_count': len(items), 'out_items': '；'.join(items)}

    def _exception_category(self):
        cat = self.env['sn.wsd.exception.category'].sudo().search([('code', '=', EXCEPTION_CATEGORY_CODE)], limit=1)
        return cat

    def _raise_exceptions(self, window_hours=4):
        """同一机台 4 小时内只开一张未关闭的「工艺参数超限」异常单，后续超限模次挂到同一单。"""
        category = self._exception_category()
        if not category:
            return
        Ticket = self.env['sn.wsd.exception.ticket'].sudo()
        for shot in self.sorted('shot_time'):
            line = shot.machine_id.production_line_id
            if not line:
                continue
            ticket = Ticket.search([('category_id', '=', category.id), ('production_line_id', '=', line.id),
                                    ('state', 'not in', ('done', 'cancelled')),
                                    ('reported_at', '>=', shot.shot_time - timedelta(hours=window_hours))],
                                   order='id desc', limit=1)
            if not ticket:
                ticket = Ticket.create({
                    'category_id': category.id,
                    'production_line_id': line.id,
                    'description': _('【工艺参数超限】机台 %(mc)s / 模具 %(m)s / 模次 %(n)s：%(items)s',
                                     mc=shot.machine_id.code, m=shot.mold_id.sn, n=shot.shot_no, items=shot.out_items),
                })
            if ticket.create_date and ticket.reported_at and ticket.reported_at > shot.shot_time + timedelta(minutes=10) \
                    and ticket.description and shot.out_items in ticket.description:
                # 网关断线缓存后补传的历史模次：异常发生时间以模次采集时间为准
                ticket.reported_at = shot.shot_time
            shot.exception_id = ticket
            ticket.impact_qty = (ticket.impact_qty or 0) + (shot.plan_id.cavity or shot.mold_id.effective_cavity or 1)

    # ------------------------------------------------------------------
    # SPC（X̄-R 控制图 + 过程能力）
    # ------------------------------------------------------------------
    @api.model
    def spc_options(self):
        machines = self.env['sn.inj.machine'].search([])
        params = [{'key': f, 'label': PARAM_NAMES[c], 'unit': PARAM_UNITS[c]} for f, c in SHOT_PARAM_MAP.items()]
        return {
            'machines': [{'id': m.id, 'name': '%s %s' % (m.code, m.name),
                          'mold': m.current_mold_id.sn or ''} for m in machines],
            'params': params,
        }

    @api.model
    def spc_data(self, machine_id, param='cycle_time', subgroup=5, limit=125):
        if param not in SHOT_PARAM_MAP:
            raise UserError(_('不支持的参数。'))
        machine = self.env['sn.inj.machine'].browse(int(machine_id))
        mold = machine.current_mold_id
        domain = [('machine_id', '=', machine.id)]
        if mold:
            domain.append(('mold_id', '=', mold.id))
        shots = self.search(domain, order='shot_time desc, id desc', limit=limit).sorted(lambda s: (s.shot_time, s.id))
        n = max(2, min(int(subgroup), 6))
        a2, d3, d4, d2 = XBAR_R_CONST[n]
        values = [s[param] for s in shots]
        groups = [values[i:i + n] for i in range(0, len(values) - n + 1, n)]
        shot_groups = [shots[i:i + n] for i in range(0, len(values) - n + 1, n)]
        means = [sum(g) / n for g in groups]
        ranges = [max(g) - min(g) for g in groups]
        labels = [fields.Datetime.context_timestamp(self, g[-1].shot_time).strftime('%m-%d %H:%M') for g in shot_groups]
        card = shots[-1:].card_id if shots else self.env['sn.inj.process.card']
        code = SHOT_PARAM_MAP[param]
        line = card.line_ids.filtered(lambda l: l.code == code)[:1]
        usl, lsl, target = (line.upper, line.lower, line.std_value) if line else (None, None, None)
        res = {'machine': '%s %s' % (machine.code, machine.name), 'mold': mold.display_name or '',
               'product': shots[-1:].product_id.display_name or '', 'card': card.display_name or '',
               'param': PARAM_NAMES[code], 'unit': PARAM_UNITS[code], 'n': n, 'count': len(values),
               'labels': labels, 'means': [round(m, 3) for m in means], 'ranges': [round(r, 3) for r in ranges],
               'usl': usl, 'lsl': lsl, 'target': target}
        if not means:
            return res
        xbarbar = sum(means) / len(means)
        rbar = sum(ranges) / len(ranges)
        sigma = rbar / d2 if rbar else 0.0
        mean_all = sum(values) / len(values)
        sd_all = math.sqrt(sum((v - mean_all) ** 2 for v in values) / (len(values) - 1)) if len(values) > 1 else 0
        res.update({
            'cl': round(xbarbar, 3), 'ucl': round(xbarbar + a2 * rbar, 3), 'lcl': round(xbarbar - a2 * rbar, 3),
            'rbar': round(rbar, 3), 'r_ucl': round(d4 * rbar, 3), 'r_lcl': round(d3 * rbar, 3),
            'sigma': round(sigma, 4), 'mean': round(mean_all, 3), 'sd': round(sd_all, 4),
            'out_spec': sum(1 for v in values if (usl is not None and v > usl) or (lsl is not None and v < lsl)),
        })
        res['ooc'] = [i for i, m in enumerate(means) if m > res['ucl'] or m < res['lcl']]
        if sigma and usl is not None and lsl is not None and usl > lsl:
            res['cp'] = round((usl - lsl) / (6 * sigma), 2)
            res['cpk'] = round(min(usl - xbarbar, xbarbar - lsl) / (3 * sigma), 2)
        if sd_all and usl is not None and lsl is not None and usl > lsl:
            res['ppk'] = round(min(usl - mean_all, mean_all - lsl) / (3 * sd_all), 2)
        return res

    # ------------------------------------------------------------------
    # 设备接口入口
    # ------------------------------------------------------------------
    @api.model
    def api_upload(self, payload):
        """payload: 单条 dict 或 {"shots": [...]}；机台/模具用编号。返回每条的超限判定。"""
        rows = payload.get('shots') if isinstance(payload.get('shots'), list) else [payload]
        Machine = self.env['sn.inj.machine']
        Mold = self.env['sn.inj.mold']
        vals_list = []
        for row in rows:
            machine = Machine.search([('code', '=', row.get('machine'))], limit=1)
            if not machine:
                raise UserError(_('机台 %s 不存在。', row.get('machine')))
            mold = Mold.search([('sn', '=', row.get('mold'))], limit=1) if row.get('mold') else machine.current_mold_id
            if not mold:
                raise UserError(_('机台 %s 未指定模具且当前无在机模具。', machine.code))
            vals = {'machine_id': machine.id, 'mold_id': mold.id, 'source': 'api',
                    'shot_no': int(row.get('shot_no') or 0) or (mold.total_usage_count + len(vals_list) + 1)}
            if row.get('time'):
                vals['shot_time'] = fields.Datetime.to_datetime(row['time'])
            for key in SHOT_PARAM_MAP:
                if row.get(key) is not None:
                    vals[key] = float(row[key])
            vals_list.append(vals)
        shots = self.create(vals_list)
        return [{'id': s.id, 'shot_no': s.shot_no, 'is_out': s.is_out, 'out_items': s.out_items or '',
                 'exception': s.exception_id.name or ''} for s in shots]
