from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

from .factory import RATINGS


def _rating(score):
    return 'A' if score >= 90 else 'B' if score >= 80 else 'C' if score >= 70 else 'D'


class SnOutKpi(models.Model):
    """代工厂绩效（按期统计）。

    准交率 = 按期到货批次 / 到货批次（到货日 ≤ 承诺交期）
    合格率 = 检验合格批次 / 检验批次（判退、让步、挑选均计不合格批）
    超耗率 = 超耗量 / 发料量（期间内确认的物料平衡；包工包料无发料不计）
    综合得分 = 准交率 × 40% + 合格率 × 40% + 物料分 20（超耗率每 1% 扣 4 分）
    评级：A ≥ 90，B ≥ 80，C ≥ 70，D < 70；回写代工厂档案，D 级自动暂停合作。
    """
    _name = 'sn.out.kpi'
    _description = '代工厂绩效'
    _order = 'date_from desc, score desc'

    factory_id = fields.Many2one('sn.out.factory', string='代工厂', required=True, index=True, ondelete='cascade')
    period = fields.Char(string='期间', required=True)
    date_from = fields.Date(string='开始日期', required=True)
    date_to = fields.Date(string='结束日期', required=True)
    order_count = fields.Integer(string='涉及代工单')
    batch_count = fields.Integer(string='到货批次')
    ontime_count = fields.Integer(string='按期批次')
    ontime_rate = fields.Float(string='准交率(%)', digits=(5, 1), aggregator='avg')
    inspect_count = fields.Integer(string='检验批次')
    pass_count = fields.Integer(string='合格批次')
    pass_rate = fields.Float(string='合格率(%)', digits=(5, 1), aggregator='avg')
    delivered_qty = fields.Integer(string='到货数量')
    accepted_qty = fields.Integer(string='合格入库')
    issued_qty = fields.Float(string='发料量', digits=(12, 1))
    excess_qty = fields.Float(string='超耗量', digits=(12, 2))
    excess_rate = fields.Float(string='超耗率(%)', digits=(5, 2), aggregator='avg')
    deduct_amount = fields.Float(string='超耗扣款(元)', digits=(12, 2))
    score = fields.Float(string='综合得分', digits=(5, 1), aggregator='avg')
    rating = fields.Selection(RATINGS, string='评级')
    note = fields.Char(string='说明')

    _factory_period_unique = models.Constraint('unique(factory_id, period)', '同一代工厂同一期间只能有一条绩效。')

    @api.model
    def compute_period(self, date_from, date_to, period=None, writeback=True):
        date_from, date_to = fields.Date.to_date(date_from), fields.Date.to_date(date_to)
        period = period or date_from.strftime('%Y-%m')
        start = datetime.combine(date_from, time.min) - timedelta(hours=8)
        end = datetime.combine(date_to, time.max) - timedelta(hours=8)
        Receipt = self.env['sn.out.receipt']
        Balance = self.env['sn.out.balance']
        result = self.browse()
        for fac in self.env['sn.out.factory'].search([]):
            rcps = Receipt.search([('factory_id', '=', fac.id), ('state', 'not in', ('draft', 'cancel')),
                                   ('date', '>=', start), ('date', '<=', end)])
            judged = rcps.filtered(lambda r: r.iqc_id.state == 'done')
            bals = Balance.search([('factory_id', '=', fac.id), ('state', '=', 'confirmed'),
                                   ('confirm_date', '>=', start), ('confirm_date', '<=', end)])
            if not rcps and not bals:
                continue
            batches = len(rcps)
            ontime = len(rcps.filtered('on_time'))
            passed = len(judged.filtered(lambda r: r.iqc_id.result == 'pass'))
            issued = sum(bals.mapped('issued_qty'))
            excess = sum(bals.mapped('excess_qty'))
            ontime_rate = ontime * 100.0 / batches if batches else 100.0
            pass_rate = passed * 100.0 / len(judged) if judged else 100.0
            excess_rate = excess * 100.0 / issued if issued else 0.0
            score = round(ontime_rate * 0.4 + pass_rate * 0.4 + max(20 - excess_rate * 4, 0), 1)
            vals = {
                'factory_id': fac.id, 'period': period, 'date_from': date_from, 'date_to': date_to,
                'order_count': len(rcps.order_id | bals.order_id), 'batch_count': batches, 'ontime_count': ontime,
                'ontime_rate': round(ontime_rate, 1), 'inspect_count': len(judged), 'pass_count': passed,
                'pass_rate': round(pass_rate, 1), 'delivered_qty': sum(rcps.mapped('qty')),
                'accepted_qty': sum(rcps.filtered(lambda r: r.state == 'done').mapped('accepted_qty')),
                'issued_qty': issued, 'excess_qty': excess, 'excess_rate': round(excess_rate, 2),
                'deduct_amount': sum(bals.mapped('deduct_amount')), 'score': score, 'rating': _rating(score),
            }
            kpi = self.search([('factory_id', '=', fac.id), ('period', '=', period)], limit=1)
            if kpi:
                kpi.write(vals)
            else:
                kpi = self.create(vals)
            result |= kpi
        if writeback:
            result._writeback()
        return result

    def _writeback(self):
        for kpi in self:
            fac = kpi.factory_id
            latest = fac.kpi_ids.sorted('date_to', reverse=True)[:1]
            if latest != kpi:
                continue
            fac.write({'rating': kpi.rating, 'rating_score': kpi.score, 'rating_period': kpi.period})
            msg = _('%(p)s 绩效：准交率 %(o).1f%%，合格率 %(q).1f%%，超耗率 %(e).2f%%，综合 %(s).1f 分，评级 %(r)s。',
                    p=kpi.period, o=kpi.ontime_rate, q=kpi.pass_rate, e=kpi.excess_rate, s=kpi.score, r=kpi.rating)
            if kpi.rating == 'D' and fac.coop_state != 'suspended':
                fac.write({'coop_state': 'suspended',
                           'suspend_reason': _('%s 绩效评级 D，自动暂停，整改验证后恢复', kpi.period)})
                msg += _(' 评级 D，已自动暂停合作。')
            elif kpi.rating in ('A', 'B') and fac.coop_state == 'trial':
                msg += _(' 试用期表现达标，可评审转为合格代工厂。')
            fac.message_post(body=msg)
        return True

    @api.model
    def _cron_monthly(self):
        today = fields.Date.context_today(self)
        first = today.replace(day=1) - relativedelta(months=1)
        last = today.replace(day=1) - timedelta(days=1)
        return self.compute_period(first, last)


class SnOutKpiWizard(models.TransientModel):
    _name = 'sn.out.kpi.wizard'
    _description = '代工厂绩效统计'

    date_from = fields.Date(string='开始日期', required=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string='结束日期', required=True, default=fields.Date.context_today)
    period = fields.Char(string='期间名称')
    writeback = fields.Boolean(string='回写代工厂评级', default=True)

    def action_compute(self):
        kpis = self.env['sn.out.kpi'].compute_period(self.date_from, self.date_to,
                                                     period=self.period or self.date_from.strftime('%Y-%m'),
                                                     writeback=self.writeback)
        return {'type': 'ir.actions.act_window', 'name': _('代工厂绩效'), 'res_model': 'sn.out.kpi',
                'view_mode': 'graph,list,pivot', 'domain': [('id', 'in', kpis.ids)]}


class SnOutKpiBoard(models.AbstractModel):
    _name = 'sn.out.kpi.board'
    _description = '代工厂绩效看板数据'

    @api.model
    def board_data(self):
        Kpi = self.env['sn.out.kpi']
        facs = self.env['sn.out.factory'].search([])
        periods = sorted(set(Kpi.search([]).mapped('period')))
        states = dict(self.env['sn.out.factory']._fields['coop_state'].selection)
        rows, trend = [], []
        for fac in facs:
            kpis = Kpi.search([('factory_id', '=', fac.id)], order='date_from')
            batches = sum(kpis.mapped('batch_count'))
            ontime = sum(kpis.mapped('ontime_count'))
            insp = sum(kpis.mapped('inspect_count'))
            passed = sum(kpis.mapped('pass_count'))
            issued = sum(kpis.mapped('issued_qty'))
            excess = sum(kpis.mapped('excess_qty'))
            last = kpis[-1:] if kpis else kpis
            rows.append({
                'id': fac.id, 'name': fac.name, 'coop_state': fac.coop_state, 'coop_label': states.get(fac.coop_state),
                'rating': fac.rating or '-', 'score': round(fac.rating_score, 1), 'period': fac.rating_period or '',
                'batches': batches, 'ontime_rate': round(ontime * 100.0 / batches, 1) if batches else None,
                'pass_rate': round(passed * 100.0 / insp, 1) if insp else None,
                'excess_rate': round(excess * 100.0 / issued, 2) if issued else 0.0,
                'deduct': round(sum(kpis.mapped('deduct_amount')), 2),
                'reject': insp - passed, 'orders': fac.order_count, 'open_orders': fac.open_order_count,
                'loans': fac.loan_count, 'capacity': fac.capacity_pcs_day,
            })
            by_p = {k.period: k.score for k in kpis}
            trend.append({'name': fac.name, 'scores': [by_p.get(p) for p in periods]})
        return {'periods': periods, 'rows': rows, 'trend': trend}
