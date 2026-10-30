from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo import Command


class PieceSettlementGenerateWizard(models.TransientModel):
    """日报工工作台（report-daily-workbench，原「从报工生成计件」原地升级）。

    两个页签：
    - 待报工（report_line_ids）：活跃报工单私有路线上的工序行，录
      OK/NG/报废与人员分配，action_submit_reports 在一个事务内逐行调
      report_operation_qty（五道闸原样），任一行被拦整批不落库并指明
      行与原因；提交后尽力自动生成计件草稿。
    - 待分配（report_ids）：现有未结算报工行（含车间终端报的）批量
      生成计件草稿；有分配的报工行原样复制，无分配的走班组默认参与人。
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
    workshop_id = fields.Many2one(
        'sn.mrp.workshop', string='Workshop',
        help='Filter the To Report tab by workshop.')
    production_line_id = fields.Many2one(
        'sn.mrp.production.line', string='Production Line',
        domain="[('workshop_id', '=', workshop_id)]",
        help='Filter the To Report tab by production line.')
    report_line_ids = fields.One2many(
        'sn.wsd.piece.report.wizard.line', 'wizard_id',
        string='To Report')

    # ------------------------------------------------------------------
    # To Allocate tab (existing caliber, allocation-aware generation)
    # ------------------------------------------------------------------

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
            if report.participant_ids:
                # 报工行带分配：参与人/比例原样复制，结算侧只读
                settlement.write({
                    'team_id': report.team_id.id,
                    'participant_ids': [Command.clear()] + [
                        Command.create({
                            'employee_id': p.employee_id.id,
                            'performance_ratio': p.performance_ratio,
                            'x_ratio_baseline': p.performance_ratio,
                            'sequence': p.sequence,
                        }) for p in report.participant_ids.sorted('sequence')],
                })
            else:
                settlement._default_team_and_participants()
            settlements |= settlement
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Settlements'),
            'res_model': 'sn.wsd.piece.settlement',
            'domain': [('id', 'in', settlements.ids)],
            'view_mode': 'list,form',
        }

    # ------------------------------------------------------------------
    # To Report tab (daily reporting entry)
    # ------------------------------------------------------------------

    @api.onchange('workshop_id', 'production_line_id', 'mes_order_id')
    def _onchange_load_report_lines(self):
        for wizard in self:
            wizard.report_line_ids = [
                (5, 0, 0)] + [
                (0, 0, vals) for vals in wizard._search_report_line_vals()]

    def _active_report_order_domain(self):
        domain = [
            ('x_manage_mode', '=', 'report'),
            ('state', 'in', ('released', 'picked', 'in_progress')),
        ]
        if self.mes_order_id:
            domain.append(('id', '=', self.mes_order_id.id))
        if self.production_line_id:
            domain.append(('production_line_id', '=', self.production_line_id.id))
        if self.workshop_id:
            domain.append(('x_workshop_id', '=', self.workshop_id.id))
        return domain

    def _search_report_line_vals(self):
        """One wizard line per operation row of every active report-mode
        order matching the workshop / line / order filters, participants
        prefilled (last allocation of the operation, else team normalized)."""
        self.ensure_one()
        Line = self.env['sn.wsd.piece.report.wizard.line']
        orders = self.env['sn.wsd.mes.order'].search(
            self._active_report_order_domain(), order='id asc')
        vals_list = []
        for order in orders:
            for op in order.x_route_operation_ids.sorted('sequence'):
                team = Line._default_team_for(order)
                team_id, participant_commands = Line._participant_prefill(
                    order, op, team)
                vals_list.append({
                    'sequence': op.sequence or 100,
                    'mes_order_id': order.id,
                    'route_operation_id': op.id,
                    'team_id': team_id,
                    'participant_ids': participant_commands,
                })
        return vals_list

    def action_submit_reports(self):
        """Whole-batch validation first, then one transaction: one
        report_operation_qty per line (all five gates unchanged). Any
        rejection rolls the whole batch back and names the line.

        The onchange preloads every reportable operation row as a
        reference: rows the clerk never filled keep zero quantities and
        are skipped, so an untouched row never blocks the batch."""
        self.ensure_one()
        lines = self.report_line_ids.filtered(
            lambda l: l.qty_ok or l.qty_ng or l.qty_scrap)
        if not lines:
            raise UserError(_(
                'Enter at least one positive quantity on a line before '
                'submitting.'))
        for index, line in enumerate(lines, start=1):
            try:
                line._validate_for_submit()
            except (UserError, ValidationError) as exc:
                raise ValidationError(_(
                    'Line %(index)s (order %(order)s, operation %(op)s): '
                    '%(reason)s', index=index,
                    order=line.mes_order_id.name,
                    op=line.route_operation_id.display_label,
                    reason=str(exc))) from exc
        created = self.env['sn.wsd.mes.operation.report']
        for index, line in enumerate(lines, start=1):
            try:
                created |= line.mes_order_id.report_operation_qty(
                    line.route_operation_id, line.qty_ok,
                    qty_ng=line.qty_ng, qty_scrap=line.qty_scrap,
                    scrap_reason=line.scrap_reason_id,
                    participant_vals=[{
                        'employee_id': p.employee_id.id,
                        'performance_ratio': p.performance_ratio,
                        'sequence': p.sequence,
                    } for p in line.participant_ids.sorted('sequence')],
                    team_id=line.team_id.id)
            except (UserError, ValidationError) as exc:
                raise ValidationError(_(
                    'Line %(index)s (order %(order)s, operation %(op)s) was '
                    'rejected: %(reason)s', index=index,
                    order=line.mes_order_id.name,
                    op=line.route_operation_id.display_label,
                    reason=str(exc))) from exc
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Daily Reporting'),
                'message': _(
                    '%(count)s operation report(s) submitted.',
                    count=len(created)),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
