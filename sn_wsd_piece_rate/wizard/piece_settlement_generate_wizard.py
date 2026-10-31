from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PieceSettlementGenerateWizard(models.TransientModel):
    """日报工工作台（report-daily-workbench，原「从报工生成计件」原地升级；
    report-daily-price-inline 简化为单页签）。

    单页签「待报工」（report_line_ids）：活跃报工单私有路线上的工序行，录
    OK/NG/报废、人员分配与单价（已配价只读、未配价现填即建主数据），
    action_submit_reports 在一个事务内逐行调 report_operation_qty（五道闸
    原样），任一行被拦整批不落库并指明行与原因；提交后尽力自动生成计件
    草稿。原「待分配」页签已删：残留（关账月/终端行/作废重开）改在报工
    台账列表勾选后批量生成（sn.wsd.mes.operation.report
    .action_generate_piece_settlement）。
    """
    _name = 'sn.wsd.piece.settlement.generate.wizard'
    _description = 'Generate Piece Settlements from Reports'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order')
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
    # To Report tab (daily reporting entry)
    # ------------------------------------------------------------------

    @api.onchange('workshop_id', 'production_line_id', 'mes_order_id')
    def _onchange_load_report_lines(self):
        for wizard in self:
            wizard.report_line_ids = [
                (5, 0, 0)] + [
                (0, 0, vals) for vals in wizard._search_report_line_vals()]

    def action_reload_lines(self):
        """Server-side twin of the onchange, called by the menu's server
        action right after create: the wizard and its lines are persisted
        BEFORE the dialog opens, so the per-line object buttons (Fill From
        Team / Split Equally / Reuse Last Allocation) run on real records.
        Object buttons on the virtual rows of an unsaved wizard fail with
        "field wizard_id is missing" -- the client saves the line alone."""
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

    def _ensure_piece_rates(self, lines):
        """report-daily-price-inline: create the typed prices into the rate
        master (company / product / operation), get-or-create so several
        lines of the same tuple share one row and an existing rate always
        wins over a typed value. Runs in the submit transaction, before
        report_operation_qty: the auto-draft hook then resolves the price
        of the very row just created."""
        Rate = self.env['sn.wsd.piece.rate'].sudo()
        for line in lines:
            if line.qty_ok <= 0 or line.piece_price > 0 \
                    or line.x_new_price <= 0:
                continue
            existing = Rate.search([
                ('company_id', '=', line.company_id.id),
                ('product_id', '=', line.mes_order_id.product_id.id),
                ('operation_id', '=',
                 line.route_operation_id.operation_id.id),
            ], limit=1)
            if not existing:
                Rate.create({
                    'company_id': line.company_id.id,
                    'product_id': line.mes_order_id.product_id.id,
                    'operation_id':
                        line.route_operation_id.operation_id.id,
                    'price': line.x_new_price,
                })

    def action_submit_reports(self):
        """Whole-batch validation first (price + allocation + quantities),
        then typed prices land in the rate table, then one transaction: one
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
        self._ensure_piece_rates(lines)
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
