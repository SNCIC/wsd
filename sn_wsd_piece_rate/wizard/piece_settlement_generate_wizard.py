from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PieceSettlementGenerateWizard(models.TransientModel):
    """从报工生成计件单：按制令单/日期筛未结算报工行，勾选批量建草稿。

    生成的草稿自带：报工行引用（1:1 占用）、qty_ok、业务日期=报工时间、
    单价快照、班组默认参与人（产线唯一活跃班组时）。
    """
    _name = 'sn.wsd.piece.settlement.generate.wizard'
    _description = 'Generate Piece Settlements from Reports'

    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order')
    report_ids = fields.Many2many(
        'sn.wsd.mes.operation.report',
        'sn_wsd_piece_generate_wizard_report_rel',
        'wizard_id', 'report_id',
        string='Unsettled Reports',
        domain=[('x_piece_settled', '=', False)],
        help='Only reports without a non-void settlement can be selected.')

    @api.onchange('date_from', 'date_to', 'mes_order_id')
    def _onchange_filters_load_reports(self):
        for wizard in self:
            wizard.report_ids = [(6, 0, wizard._search_unsettled_reports().ids)]

    def _search_unsettled_reports(self):
        self.ensure_one()
        domain = [('x_piece_settled', '=', False)]
        if self.mes_order_id:
            domain.append(('mes_order_id', '=', self.mes_order_id.id))
        if self.date_from:
            domain.append(('reported_at', '>=', f'{self.date_from} 00:00:00'))
        if self.date_to:
            domain.append(('reported_at', '<=', f'{self.date_to} 23:59:59'))
        return self.env['sn.wsd.mes.operation.report'].search(
            domain, order='reported_at desc')

    def action_generate(self):
        self.ensure_one()
        if not self.report_ids:
            raise UserError(_('Select at least one report to settle.'))
        Settlement = self.env['sn.wsd.piece.settlement']
        settlements = Settlement
        for report in self.report_ids:
            settlement = Settlement.create({
                'mes_order_id': report.mes_order_id.id,
                'route_operation_id': report.route_operation_id.id,
                'operation_report_id': report.id,
                'qty_ok': report.qty_ok,
                'date': report.reported_at.date() if report.reported_at
                else fields.Date.context_today(self),
            })
            settlement._resolve_rate_price()
            settlement._default_team_and_participants()
            settlements |= settlement
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Settlements'),
            'res_model': 'sn.wsd.piece.settlement',
            'domain': [('id', 'in', settlements.ids)],
            'view_mode': 'list,form',
        }
