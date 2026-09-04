from odoo import api, fields, models


class MesOperationReport(models.Model):
    """piece-rate 扩展：报工行的计件占用状态（非侵入，仅追加字段）。

    一笔报工行最多存在一张未作废的计件单（草稿即占用，作废释放）——
    x_piece_settled 即该口径的只读判定，供向导/开单 domain 过滤。
    """
    _inherit = 'sn.wsd.mes.operation.report'

    piece_settlement_ids = fields.One2many(
        'sn.wsd.piece.settlement', 'operation_report_id',
        string='Piece Settlements')
    x_piece_settled = fields.Boolean(
        string='Piece Settled',
        compute='_compute_piece_settled',
        search='_search_piece_settled',
        help='True when a non-void piece settlement references this report.')

    @api.depends('piece_settlement_ids.state')
    def _compute_piece_settled(self):
        for report in self:
            report.x_piece_settled = bool(
                report.piece_settlement_ids.filtered(lambda s: s.state != 'void'))

    def _search_piece_settled(self, operator, value):
        # Odoo 19 会把 '= True' 规范成 ('in', [True]) 传入，value 可能是集合
        values = value if isinstance(value, (list, tuple, set)) else [value]
        truthy = any(bool(v) for v in values)
        want_settled = truthy if operator in ('=', 'in') else not truthy
        settlements = self.env['sn.wsd.piece.settlement'].search([
            ('state', '!=', 'void'),
            ('operation_report_id', '!=', False),
        ])
        settled_ids = settlements.mapped('operation_report_id').ids
        return [('id', 'in' if want_settled else 'not in', settled_ids)]
