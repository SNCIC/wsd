from odoo import _, api, fields, models
from odoo.exceptions import UserError

STAGES = [('prepare', '备料/排产'), ('trial', '试模/首件'), ('mass', '量产中'), ('finish', '生产完毕待交')]


class SnOutProgress(models.Model):
    """代工厂进度回报：人工登记或接口回报（POST /api/outsource/progress）。"""
    _name = 'sn.out.progress'
    _description = '代工进度回报'
    _order = 'date desc, id desc'

    order_id = fields.Many2one('sn.out.order', string='代工单', required=True, index=True, ondelete='cascade')
    factory_id = fields.Many2one(related='order_id.factory_id', store=True, string='代工厂')
    product_id = fields.Many2one(related='order_id.product_id', string='产品')
    order_qty = fields.Integer(related='order_id.qty', string='代工数量')
    date = fields.Datetime(string='回报时间', default=fields.Datetime.now, required=True)
    stage = fields.Selection(STAGES, string='生产阶段', default='mass')
    produced_qty = fields.Integer(string='累计已产(件)', required=True)
    good_qty = fields.Integer(string='厂内良品(件)')
    shots = fields.Integer(string='累计模次')
    progress_pct = fields.Float(string='完成(%)', compute='_compute_pct', store=True, digits=(5, 1))
    source = fields.Selection([('manual', '人工登记'), ('api', '接口回报')], string='来源', default='manual')
    reporter = fields.Char(string='回报人')
    note = fields.Char(string='说明')

    @api.depends('produced_qty', 'order_id.qty')
    def _compute_pct(self):
        for rec in self:
            rec.progress_pct = round(rec.produced_qty * 100.0 / rec.order_id.qty, 1) if rec.order_id.qty else 0

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for rec in recs:
            last = rec.order_id.progress_ids.filtered(lambda p: p.id != rec.id and p.date <= rec.date).sorted('date')[-1:]
            if last and rec.produced_qty < last.produced_qty:
                raise UserError(_('累计已产 %(n)s 小于上次回报 %(l)s，请核对（回报为累计数）。',
                                  n=rec.produced_qty, l=last.produced_qty))
        recs.order_id._after_progress()
        return recs

    @api.model
    def api_report(self, payload):
        """接口：{"token": "...", "order": "DG2611-0001", "produced_qty": 5200, "shots": 5200,
        "good_qty": 5150, "stage": "mass", "note": "...", "reporter": "..."}，token 为代工厂进度接口密钥。"""
        Order = self.env['sn.out.order'].sudo()
        order = Order.search([('name', '=', payload.get('order'))], limit=1)
        if not order:
            raise UserError(_('代工单 %s 不存在。', payload.get('order')))
        if not payload.get('token') or payload.get('token') != order.factory_id.sudo().api_token:
            raise UserError(_('接口密钥无效。'))
        try:
            qty = int(payload.get('produced_qty'))
        except (TypeError, ValueError):
            raise UserError(_('produced_qty 必须为整数（累计已产件数）。'))
        stage = payload.get('stage') or 'mass'
        if stage not in dict(STAGES):
            raise UserError(_('stage 取值无效：%s', stage))
        prog = order.report_progress(qty, shots=int(payload.get('shots') or 0), stage=stage,
                                     note=payload.get('note'), source='api', good_qty=int(payload.get('good_qty') or 0))
        if payload.get('reporter'):
            prog.reporter = payload['reporter']
        return {'order': order.name, 'produced_qty': order.produced_qty, 'progress_pct': prog.progress_pct,
                'risk_level': order.risk_level, 'risk_text': order.risk_text or ''}
