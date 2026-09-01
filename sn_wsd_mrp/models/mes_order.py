from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .constants import SIDE_LABELS, SIDE_SELECTION


class MesOrder(models.Model):
    """MES Production Order (制令单).

    The single scheduling + execution document for the electronic-line MES.
    Scheduling (排产) happens exclusively through the scheduling wizard opened
    from the MO form (架构设计 3.1): no draft, no confirmation step, the record
    is ``released`` immediately and participates in the over-scheduling check.
    "日计划" is just a grouped, read-only view of these orders (by date + line),
    not a separate model.
    """
    _name = 'sn.wsd.mes.order'
    _description = 'MES Production Order'
    _order = 'production_id, date_plan, id'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(
        string='MES Order No.', required=True, copy=False, readonly=True,
        default=lambda self: _('New'), index=True,
    )
    production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', required=True,
        ondelete='cascade', index=True, check_company=True, tracking=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Product',
        related='production_id.product_id', store=True,
    )
    production_line_id = fields.Many2one(
        'sn.mrp.production.line', string='Production Line', required=True,
        check_company=True, tracking=True,
    )
    date_plan = fields.Date(string='Plan Date', required=True, tracking=True)
    x_date_plan_end = fields.Date(
        string='Plan Date End', compute='_compute_date_plan_end', store=True,
        help='Day after the plan date; used as the stop bound of the Gantt pill '
             '(each MES order occupies its whole planned day).',
    )
    planned_qty = fields.Float(string='Planned Quantity', required=True, tracking=True)
    x_side = fields.Selection(
        SIDE_SELECTION,
        string='Production Side', required=True, default='single',
        index=True, tracking=True,
        help='Board side this order produces. Over-scheduling is checked per '
             'side: Top and Bottom may each cover the full MO quantity. '
             'Single-sided products are fixed to Single.',
    )
    picked_qty = fields.Float(
        string='Picked Quantity', compute='_compute_picked_qty', store=True,
        tracking=True,
        help='Finished-unit quantity accumulated from done material pickings.',
    )
    x_over_picked_qty = fields.Float(
        string='Over-picked Quantity', compute='_compute_x_over_picked_qty',
        store=True, tracking=True,
        help='Finished-unit quantity accumulated from done over-pick '
             'pickings (issued beyond the plan, with a reason).',
    )
    produced_qty = fields.Float(
        string='Produced Quantity', compute='_compute_execution_qty', store=True,
        help='Mirror of the output quantity, kept as the aggregation source '
             'of the manufacturing order MES figures.',
    )
    state = fields.Selection(
        [('released', 'Released'),
         ('picked', 'Picked'),
         ('in_progress', 'In Progress'),
         ('done', 'Done'),
         ('cancelled', 'Cancelled')],
        string='State', default='released', required=True, tracking=True,
        copy=False, index=True,
    )
    picking_ids = fields.One2many(
        'stock.picking', 'x_mes_order_id', string='Material Pickings',
    )
    picking_count = fields.Integer(compute='_compute_picking_count')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True,
    )
    active = fields.Boolean(default=True)
    # ------------------------------------------------------------------
    # route execution (过站 / 报工)
    # ------------------------------------------------------------------
    x_manage_mode = fields.Selection(
        [('station', 'Station Tracking'), ('report', 'Operation Reporting')],
        string='Management Mode', default='station', required=True,
        help='Station: SNs enter/leave each operation one by one.\n'
             'Report: operations are reported by quantity, no SN tracking.\n'
             'Locked once the order goes online.',
    )
    x_is_dual_side_non_final = fields.Boolean(
        string='Dual-Sided Non-Final Side',
        compute='_compute_x_is_dual_side_non_final',
        help='True when this order is a T-side (non-final) order of a '
             'dual-sided product: it closes without stock receipt (the '
             'paired B-side order does the final completion). Controls the '
             '"Close" vs "Complete" button visibility.',
    )

    @api.depends('x_side', 'product_id.x_board_side')
    def _compute_x_is_dual_side_non_final(self):
        for order in self:
            order.x_is_dual_side_non_final = (
                order.product_id.x_board_side == 'double'
                and order.x_side == 'top'
            )
    x_online_date = fields.Datetime(
        string='Online Since', readonly=True, copy=False,
        help='Set by the "Go Online" action. SNs may only be fed in after it.',
    )
    x_online_log_ids = fields.One2many(
        'sn.wsd.mes.order.log', 'mes_order_id', string='Online Log',
    )
    # 冗余车间（来自产线）：在线制令单等列表直接展示/分组
    x_workshop_id = fields.Many2one(
        'sn.mrp.workshop', related='production_line_id.workshop_id',
        string='Workshop', store=True, index=True,
    )
    x_online_by = fields.Many2one(
        'res.users', string='Online By', compute='_compute_x_online_by',
        help='User of the latest "go online" log line.')

    x_mes_route_id = fields.Many2one(
        'sn.wsd.mes.order.route', string='MES Route', readonly=True, copy=False,
        index=True, ondelete='set null',
    )
    # Counter configuration (private route snapshot) — editable on the order
    # form; the server validates targets against the private graph on save.
    x_daily_input_operation_id = fields.Many2one(
        related='x_mes_route_id.x_daily_input_operation_id', readonly=False,
        string='制令单投入工序')
    x_daily_output_operation_id = fields.Many2one(
        related='x_mes_route_id.x_daily_output_operation_id', readonly=False,
        string='制令单产出工序')
    x_material_operation_id = fields.Many2one(
        related='x_mes_route_id.x_material_operation_id', readonly=False,
        string='物料关联工序')
    x_workorder_input_operation_id = fields.Many2one(
        related='x_mes_route_id.x_workorder_input_operation_id', readonly=False,
        string='工单投入工序')
    x_aging_start_operation_id = fields.Many2one(
        related='x_mes_route_id.x_aging_start_operation_id', readonly=False,
        string='老化开始工序')
    x_aging_end_operation_id = fields.Many2one(
        related='x_mes_route_id.x_aging_end_operation_id', readonly=False,
        string='老化结束工序')
    # Execution quantities (event-driven stored computes, always consistent
    # with the history/wip/report rows written by the very same transaction):
    # station mode counts SNs at the counter operations, report mode sums
    # the reported quantity there. Counters not configured -> stays 0.
    sn_history_ids = fields.One2many(
        'sn.wsd.serial.operation.history', 'mes_order_id',
    )
    sn_wip_ids = fields.One2many(
        'sn.wsd.serial.wip', 'mes_order_id',
    )
    sn_report_ids = fields.One2many(
        'sn.wsd.mes.operation.report', 'mes_order_id',
    )
    x_input_qty = fields.Float(
        string='投入数量', compute='_compute_execution_qty', store=True,
        help='SNs fed into this order at the daily input operation '
             '(counted on entry); reported quantity in report mode.',
    )
    x_output_qty = fields.Float(
        string='产出数量', compute='_compute_execution_qty', store=True,
        help='SNs that left the daily output operation with result OK; '
             'reported quantity in report mode.',
    )
    x_workorder_input_qty = fields.Float(
        string='工单投入数量', compute='_compute_execution_qty', store=True,
        help='SNs that passed the work-order input operation; reported '
             'quantity in report mode.',
    )
    x_done_qty = fields.Float(
        string='完工入库数量', copy=False,
        help='Accumulated quantity received through completion receipts. '
             'The order turns Done once this reaches the output quantity.',
    )
    x_done_date = fields.Datetime(string='最后完工时间', copy=False, readonly=True)
    x_partner_id = fields.Many2one(
        'res.partner', string='客户', compute='_compute_x_partner', store=True,
        help='Customer resolved from the source sales order of the '
             'manufacturing order (empty for stock orders).',
    )

    @api.depends('production_id')
    def _compute_x_partner(self):
        for order in self:
            partner = self.env['res.partner']
            mo = order.production_id
            if 'procurement_group_id' in mo._fields:
                group = mo.procurement_group_id
                # sale_order_id only exists when sale_stock is installed
                if group and 'sale_order_id' in group._fields:
                    partner = group.sale_order_id.partner_id
            if not partner and mo.origin:
                so = self.env['sale.order'].sudo().search(
                    [('name', '=', mo.origin)], limit=1)
                partner = so.partner_id
            order.x_partner_id = partner

    x_route_operation_ids = fields.One2many(
        'sn.wsd.mes.order.route.operation', 'mes_order_id',
        string='工序数量',
        help='Read-only per-operation counters mirroring the flow canvas.',
    )

    @api.depends(
        'x_manage_mode',
        'x_mes_route_id.x_daily_input_operation_id',
        'x_mes_route_id.x_daily_output_operation_id',
        'x_mes_route_id.x_workorder_input_operation_id',
        'sn_history_ids.route_operation_id', 'sn_history_ids.result',
        'sn_wip_ids.route_operation_id',
        'sn_report_ids.route_operation_id',
        'sn_report_ids.qty_ok', 'sn_report_ids.qty_ng', 'sn_report_ids.qty_scrap',
    )
    def _compute_execution_qty(self):
        for order in self:
            route = order.x_mes_route_id
            if order.x_manage_mode == 'report':
                def _reported(op):
                    reports = op.report_ids if op else False
                    return sum(reports.mapped(
                        lambda r: r.qty_ok + r.qty_ng + r.qty_scrap)) if reports else 0.0
                def _ok(op):
                    return sum(op.report_ids.mapped('qty_ok')) if op else 0.0
                order.x_input_qty = _reported(route.x_daily_input_operation_id)
                order.x_output_qty = _ok(route.x_daily_output_operation_id)
                order.x_workorder_input_qty = _reported(route.x_workorder_input_operation_id)
            else:
                def _entered(op):
                    # wip and history are mutually exclusive per (SN, op):
                    # the wip row is deleted as its history row is written.
                    # 台数按 SN 去重：复测多行只算一台。
                    if not op:
                        return 0
                    sn_ids = set(
                        op.serial_history_ids.mapped('serial_identity_id').ids)
                    sn_ids |= set(
                        op.serial_wip_ids.mapped('serial_identity_id').ids)
                    return len(sn_ids)
                out_op = route.x_daily_output_operation_id
                order.x_output_qty = len(set(
                    out_op.serial_history_ids
                    .filtered(lambda h: h.result == 'ok')
                    .mapped('serial_identity_id').ids)) if out_op else 0.0
                order.x_input_qty = _entered(route.x_daily_input_operation_id)
                order.x_workorder_input_qty = _entered(route.x_workorder_input_operation_id)
            order.produced_qty = order.x_output_qty

    _mes_order_name_uniq = models.Constraint(
        'unique(production_id, name)',
        'The MES order reference must be unique per manufacturing order.',
    )

    # ------------------------------------------------------------------
    # scheduling rules -- the server-side truth (架构设计 3.1):
    # whole units, active line, no over-scheduling (per side), under-
    # scheduling allowed. Sides are independent: a full Top side never
    # blocks scheduling the Bottom side of the same MO.
    # ------------------------------------------------------------------
    @api.constrains('production_id', 'production_line_id', 'planned_qty', 'state', 'x_side')
    def _check_scheduling_rules(self):
        for order in self:
            if order.state == 'cancelled' or not order.production_id:
                continue
            if order.planned_qty <= 0:
                raise ValidationError(_('The scheduled quantity must be greater than 0.'))
            if order.planned_qty != int(order.planned_qty):
                raise ValidationError(_('The scheduled quantity must be a whole number of units.'))
            if order.production_line_id and not order.production_line_id.active:
                raise ValidationError(_(
                    'Production line %(line)s is disabled and cannot be scheduled.',
                    line=order.production_line_id.display_name,
                ))
            mo = order.production_id
            siblings = self.search([
                ('production_id', '=', mo.id),
                ('state', '!=', 'cancelled'),
                ('x_side', '=', order.x_side),
            ])
            total = sum(siblings.mapped('planned_qty'))
            if total > mo.product_qty + 0.0001:
                already = total - order.planned_qty
                raise ValidationError(_(
                    'Over-scheduling: the total %(side)s-side scheduled quantity '
                    'of %(mo)s (%(total)s) would exceed its quantity (%(mo_qty)s). '
                    'Remaining schedulable on this side: %(remaining)s.',
                    side=_(SIDE_LABELS[order.x_side]), mo=mo.display_name,
                    total=total, mo_qty=mo.product_qty,
                    remaining=max(mo.product_qty - already, 0.0),
                ))

    # ------------------------------------------------------------------
    # the MES order side must match the product's declared board side type;
    # drawing products must declare one at all (the route snapshot raises
    # the same rule inside create, this covers later writes)
    # ------------------------------------------------------------------
    @api.constrains('x_side', 'product_id')
    def _check_side_matches_board(self):
        for order in self:
            board = order.product_id.x_board_side
            if order.product_id.default_code and not board:
                raise ValidationError(_(
                    'Product %(product)s has a drawing number but no board '
                    'side type declared. Declare it on the product before '
                    'scheduling.', product=order.product_id.display_name))
            if board == 'single' and order.x_side != 'single':
                raise ValidationError(_(
                    'Product %(product)s is a single-sided board; its MES orders '
                    'must stay on the Single side.', product=order.product_id.display_name))
            if board == 'double' and order.x_side not in ('top', 'bottom'):
                raise ValidationError(_(
                    'Product %(product)s is a double-sided board; its MES orders '
                    'must run on the Top (T) or Bottom (B) side.',
                    product=order.product_id.display_name))

    # ------------------------------------------------------------------
    # Gantt stop bound: an order occupies its whole planned day
    # ------------------------------------------------------------------
    @api.depends('date_plan')
    def _compute_date_plan_end(self):
        for order in self:
            order.x_date_plan_end = order.date_plan and order.date_plan + timedelta(days=1)

    # ------------------------------------------------------------------
    # picked_qty = accumulated finished units covered by done pickings
    # ------------------------------------------------------------------
    @api.depends('picking_ids.x_mes_order_qty', 'picking_ids.state',
                 'picking_ids.x_is_over_pick')
    def _compute_picked_qty(self):
        for order in self:
            # 净领口径（mes-picking-lifecycle R2/R3）：退货单的台数为负数，
            # 直接求和即净额；超领单走单独台账，不计入；未验证/取消不参与
            done = order.picking_ids.filtered(
                lambda p: p.state == 'done' and not p.x_is_over_pick)
            order.picked_qty = sum(done.mapped('x_mes_order_qty'))

    @api.depends('picking_ids.x_mes_order_qty', 'picking_ids.state',
                 'picking_ids.x_is_over_pick')
    def _compute_x_over_picked_qty(self):
        for order in self:
            done_over = order.picking_ids.filtered(
                lambda p: p.state == 'done' and p.x_is_over_pick)
            order.x_over_picked_qty = sum(done_over.mapped('x_mes_order_qty'))

    # ------------------------------------------------------------------
    # reference = MO name + per-MO sequence, with a row lock to avoid races
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                mo_id = vals.get('production_id')
                if mo_id:
                    self.env.cr.execute('SELECT id FROM mrp_production WHERE id = %s FOR UPDATE', [mo_id])
                    mo = self.env['mrp.production'].browse(mo_id)
                    existing = self.search_count([('production_id', '=', mo_id)])
                    vals['name'] = '%s-%d' % (mo.name or 'MO', existing + 1)
                else:
                    vals['name'] = _('New')
        orders = super().create(vals_list)
        # Route materialization: every MES order carries its own private
        # route from birth (fails hard when the drawing has no live route).
        orders._setup_route()
        return orders

    # ------------------------------------------------------------------
    # already-released orders are immutable except via cancel+reschedule (PRD R5)
    # ------------------------------------------------------------------
    def write(self, vals):
        # Only lifecycle fields may move; core scheduling fields (MO/line/
        # date/qty/side) are frozen once released.
        frozen = {'production_id', 'production_line_id', 'date_plan', 'planned_qty', 'x_side'}
        if frozen.intersection(vals):
            for order in self:
                if order.state not in ('cancelled',) and order.id:
                    raise ValidationError(_(
                        'MES order %(name)s is already released; cancel it and '
                        'reschedule instead of editing it.', name=order.name,
                    ))
        if 'x_manage_mode' in vals:
            for order in self:
                if order.x_online_date:
                    raise ValidationError(_(
                        'MES order %(name)s is already online; its management '
                        'mode can no longer be changed.', name=order.name))
        return super().write(vals)

    # ------------------------------------------------------------------
    # route lifecycle: setup / online / sync from the common route
    # ------------------------------------------------------------------
    def _setup_route(self):
        MesRoute = self.env['sn.wsd.mes.order.route']
        for order in self:
            if order.x_mes_route_id:
                continue
            order.x_mes_route_id = MesRoute._build_from_common(order).id

    def action_online_force(self):
        """Go Online button variant: takes the MES order occupying the
        production line offline first (one online order per line)."""
        return self.action_online(force=True)

    def action_online(self, force=False):
        """Put the order online: SN feeding is allowed from this moment on,
        the mode is locked and the common route stops auto-syncing in.
        ``force`` takes the MES order currently occupying the production
        line offline first (one online order per line)."""
        for order in self:
            if order.x_online_date:
                raise ValidationError(_(
                    'MES order %(name)s is already online.', name=order.name))
            if order.state == 'cancelled':
                raise ValidationError(_(
                    'MES order %(name)s is cancelled and cannot go online.',
                    name=order.name))
            # 排产→领料→上线：领料不可跳过（mes-picking-lifecycle R1），
            # 存在任何未取消领料单即视为"领过"，宽松口径防误拦
            if not order.picking_ids.filtered(lambda p: p.state != 'cancel'):
                raise ValidationError(_(
                    'MES order %(name)s has no material requisition yet; '
                    'issue material before going online.', name=order.name))
            # 一条产线同一时刻只能有一张在线制令单：默认拦下并指明占
            # 用者；force 模式（强制上线）先把占用单下线再上线本单
            occupying = self.search([
                ('production_line_id', '=', order.production_line_id.id),
                ('id', '!=', order.id),
                ('state', 'not in', ('cancelled', 'done')),
                ('x_online_date', '!=', False),
            ])
            if occupying:
                if not force:
                    raise ValidationError(_(
                        'Production line %(line)s already runs online MES order '
                        '%(other)s; take it offline first or force this one '
                        'online (which takes %(other)s offline).',
                        line=order.production_line_id.display_name or '-',
                        other=', '.join(occupying.mapped('name'))))
                occupying.action_offline()
            order.x_online_date = fields.Datetime.now()
            # 正常业务序（排产→领料→上线）走完的单停在 picked：
            # 上线即投产，released/picked 都转入 in_progress，否则
            # action_complete 的 in_progress 门槛会把正规流程卡死
            if order.state in ('released', 'picked'):
                order.state = 'in_progress'
            self.env['sn.wsd.mes.order.log'].create(
                {'mes_order_id': order.id, 'action': 'online'})

    def action_offline(self):
        """Take the order offline: feeding NEW SNs at start operations
        stops from this moment on. Boards already in progress stay bound
        to this order and keep flowing until they leave the end operation
        (产出不需要在线); a log line keeps who/when."""
        for order in self:
            if not order.x_online_date:
                raise ValidationError(_(
                    'MES order %(name)s is not online.', name=order.name))
            order.x_online_date = False
            self.env['sn.wsd.mes.order.log'].create(
                {'mes_order_id': order.id, 'action': 'offline'})


    def _compute_x_online_by(self):
        # the log is ordered date desc: the first online line is the latest
        Log = self.env['sn.wsd.mes.order.log']
        for order in self:
            order.x_online_by = Log.search([
                ('mes_order_id', '=', order.id),
                ('action', '=', 'online'),
            ], limit=1).user_id

    def action_sync_route(self):
        """Re-sync the private route from the current common route.

        Only allowed before going online; rows with execution records are
        frozen inside the sync itself. Accepting the common version resets
        the customized flag (the order follows the common route again)."""
        blocked = self.filtered(lambda o: o.x_online_date)
        if blocked:
            raise ValidationError(_(
                'MES order %(name)s is in production; the common route can no '
                'longer be synced into it.', name=', '.join(blocked.mapped('name'))))
        for order in self:
            route, graph = order.x_mes_route_id._resolve_common_route(order)
            order.x_mes_route_id._apply_graph(graph, route)
            order.x_mes_route_id.is_customized = False

    def action_save_route_graph(self, graph):
        """Local edit of the private route (from the order's flow editor).

        Edits only the private tables — the common route is never touched.
        Cancelled/done orders are read-only."""
        blocked = self.filtered(lambda o: o.state in ('cancelled', 'done'))
        if blocked:
            raise ValidationError(_(
                'MES order %(name)s is closed; its route can no longer be '
                'edited.', name=', '.join(blocked.mapped('name'))))
        for order in self:
            if not order.x_mes_route_id:
                raise ValidationError(_(
                    'MES order %(name)s has no private route yet.', name=order.name))
            order.x_mes_route_id.save_route_graph(graph)
        return True

    def get_route_canvas(self):
        """One-shot payload for the embedded flow editor:
        graph + per-node execution state + frozen row ids + editability."""
        self.ensure_one()
        order = self
        mr = order.x_mes_route_id
        if not mr:
            return {'graph': {'nodes': [], 'edges': []}, 'states': {},
                    'frozen_ids': [], 'editable': False, 'reason': 'no-route'}
        frozen_ids = mr.operation_ids._has_execution_records().ids
        editable = order.state not in ('cancelled', 'done')
        return {
            'graph': mr.get_route_graph(),
            'states': mr._execution_state_map(),
            'frozen_ids': frozen_ids,
            'editable': editable,
            'is_customized': mr.is_customized,
        }

    # ------------------------------------------------------------------
    # execution: reachability / station mode / report mode
    # ------------------------------------------------------------------
    def get_reachable_operations(self, serial_identity=None):
        """Operations currently enterable/reportable.

        station mode: pass the SN; report mode: omit it."""
        self.ensure_one()
        # no online gate here: going online only gates *feeding* new SNs at
        # start operations -- boards already fed keep flowing (and reporting
        # keeps running) after the order goes offline
        ops = self.x_mes_route_id.operation_ids
        return ops._reachable_operations(self, serial_identity)

    # ------------------------------------------------------------------
    # station entry by work center (the field-facing interface)
    # ------------------------------------------------------------------
    def _station_successors(self, route_operation):
        """Direct successors of a route operation on this order's route.

        Used by the one-scan pass kernel: after an operation completes a
        board with OK, the board is auto-parked at the next station when
        exactly one successor exists (a fork cannot auto-route -- the
        branch station's own scan picks the board up)."""
        self.ensure_one()
        return self.x_mes_route_id.operation_ids.filtered(
            lambda r: route_operation in r.blocked_by_ids)

    def _resolve_route_operation(self, workcenter):
        """Map a work center onto the private-route row of this order.

        Chain: workcenter.x_operation_id -> the unique route row carrying
        that standard operation. Workshop must match the order's line."""
        self.ensure_one()
        if not workcenter or not workcenter.active:
            raise ValidationError(_(
                'Work center %(wc)s is disabled.',
                wc=workcenter.display_name if workcenter else '-'))
        operation = workcenter.x_operation_id
        if not operation:
            raise ValidationError(_(
                'Work center %(wc)s is not linked to a standard operation.',
                wc=workcenter.display_name))
        workshop = self.production_line_id.workshop_id
        if workcenter.x_workshop_id != workshop:
            raise ValidationError(_(
                'Work center %(wc)s belongs to workshop %(wc_shop)s, but MES '
                'order %(order)s runs in workshop %(order_shop)s.',
                wc=workcenter.display_name,
                wc_shop=workcenter.x_workshop_id.display_name or '-',
                order=self.name, order_shop=workshop.display_name or '-'))
        route_op = self.x_mes_route_id.operation_ids.filtered(
            lambda op: op.operation_id == operation)
        if not route_op:
            raise ValidationError(_(
                'Operation %(op)s (work center %(wc)s) is not part of the '
                'process route of MES order %(order)s.',
                op=operation.display_name, wc=workcenter.display_name,
                order=self.name))
        return route_op

    def _resolve_serial_identity(self, sn, at_start):
        """SN by name: auto-registered at start operations, must exist later."""
        Serial = self.env['sn.wsd.serial.identity']
        if isinstance(sn, models.BaseModel):
            return sn
        sn_name = (sn or '').strip()
        if not sn_name:
            raise ValidationError(_('Physical SN is required.'))
        if at_start:
            return Serial.sudo().get_or_create(
                sn_name, self.company_id, origin_type='manual')
        serial = Serial.search([
            ('name', '=', sn_name),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not serial:
            raise ValidationError(_(
                'SN %(sn)s is unknown; SNs register themselves when they '
                'enter a start operation.', sn=sn_name))
        return serial

    def scan_enter(self, sn, workcenter):
        """Field-facing station entry: SN + work center.

        The start operation additionally requires the work center to sit on
        the order's own production line. Writes run as sudo so shop-floor
        operators only need read access."""
        self.ensure_one()
        route_operation = self._resolve_route_operation(workcenter)
        if route_operation.x_allow_entry \
                and workcenter.x_production_line_id != self.production_line_id:
            raise ValidationError(_(
                'The work center of a start operation must sit on the '
                'production line of the MES order: %(wc)s is on %(wc_line)s, '
                'order %(order)s runs on %(order_line)s.',
                wc=workcenter.display_name,
                wc_line=workcenter.x_production_line_id.display_name or '-',
                order=self.name,
                order_line=self.production_line_id.display_name or '-'))
        serial = self._resolve_serial_identity(
            sn, at_start=route_operation.x_allow_entry)
        self.enter_station(serial, route_operation, workcenter=workcenter)
        return serial

    def enter_station(self, serial_identity, route_operation, workcenter=False):
        """Station mode: an SN enters an operation (its first station must be
        a start operation; later stations follow OR-reachability)."""
        self.ensure_one()
        if self.x_manage_mode != 'station':
            raise ValidationError(_(
                'MES order %(name)s is managed by operation reporting; SN '
                'station tracking is not available.', name=self.name))
        if route_operation.x_allow_entry and not self.x_online_date:
            # feeding a new SN into a start operation requires the order to
            # be online; boards already in flow keep moving between stations
            raise ValidationError(_(
                'MES order %(name)s is offline: new SNs cannot be fed in. '
                'Boards already in progress keep flowing until they leave '
                'the end operation.', name=self.name))
        Wip = self.env['sn.wsd.serial.wip']
        current = Wip.search([('serial_identity_id', '=', serial_identity.id)], limit=1)
        if current:
            raise ValidationError(_(
                'SN %(sn)s is in progress at operation %(op)s of order '
                '%(order)s; it must leave that station first.',
                sn=serial_identity.name,
                op=current.route_operation_id.display_label,
                order=current.mes_order_id.name))
        History = self.env['sn.wsd.serial.operation.history']
        walked = History.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ])
        finished = walked.filtered(
            lambda h: h.result == 'ok' and h.route_operation_id.x_allow_exit)
        if finished:
            raise ValidationError(_(
                'SN %(sn)s already left MES order %(order)s through end '
                'operation %(op)s; it cannot be fed into this order again.',
                sn=serial_identity.name, order=self.name,
                op=finished[0].route_operation_id.display_label))
        scrapped = walked.filtered(lambda h: h.result == 'scrap')
        if scrapped:
            raise ValidationError(_(
                'SN %(sn)s was scrapped at operation %(op)s of MES order '
                '%(order)s; it cannot be fed into this order again.',
                sn=serial_identity.name, order=self.name,
                op=scrapped[0].route_operation_id.display_label))
        # an SN stays bound to the order it was first fed into until it
        # leaves that order through an end operation (产出解绑)
        other_histories = History.search([
            ('serial_identity_id', '=', serial_identity.id),
        ]).filtered(lambda h: h.mes_order_id != self)
        for bound_order in other_histories.mapped('mes_order_id'):
            left_through_exit = History.search([
                ('serial_identity_id', '=', serial_identity.id),
                ('mes_order_id', '=', bound_order.id),
                ('result', '=', 'ok'),
            ]).filtered(lambda h: h.route_operation_id.x_allow_exit)
            if not left_through_exit:
                raise ValidationError(_(
                    'SN %(sn)s is still bound to MES order %(order)s; it '
                    'must leave that order through its end operation before '
                    'being fed into another one.',
                    sn=serial_identity.name, order=bound_order.name))
        # 过站次数上限：OK 与 NG 各占一次（测试工序复测口径）；截断点由
        # sn_wsd_repair 注入（最新已关维修单的关单时间，之前的行不计=清零
        # 重满）。尾站（结束/产出工序）固定一次，优先于工序配置。
        cutoff = self.env.context.get('sn_wsd_pass_cutoff')
        passes = walked.filtered(
            lambda h: h.route_operation_id == route_operation
            and h.result in ('ok', 'ng')
            and (not cutoff or h.out_date > cutoff))
        cap = 1 if route_operation.x_allow_exit \
            else route_operation.operation_id.x_max_test_count
        if len(passes) >= cap:
            raise ValidationError(_(
                'SN %(sn)s reached the pass limit (%(limit)s) of operation '
                '%(op)s; send it to repair.',
                sn=serial_identity.name, limit=cap,
                op=route_operation.display_label))
        if not walked and not route_operation.x_allow_entry:
            raise ValidationError(_(
                'SN %(sn)s has not entered MES order %(order)s yet; it must '
                'be fed in from a start operation (%(op)s is not one).',
                sn=serial_identity.name, order=self.name,
                op=route_operation.display_label))
        # 维修回流目标（关单授权的进站种子）跳过可达性；其余按
        # "前驱在截断点后有 OK" 推进（无维修时截断点为空=全部历史）。
        seed_ids = self.env.context.get('sn_wsd_repair_seed_ids', [])
        if route_operation.id not in seed_ids:
            reachable = self.get_reachable_operations(serial_identity)
            if route_operation not in reachable:
                raise ValidationError(_(
                    'Operation %(op)s is not reachable for SN %(sn)s: none of its '
                    'predecessors %(preds)s is completed yet.',
                    op=route_operation.display_label, sn=serial_identity.name,
                    preds=', '.join(route_operation.blocked_by_ids.mapped('display_label')) or '-'))
        Wip.sudo().create({
            'serial_identity_id': serial_identity.id,
            'mes_order_id': self.id,
            'route_operation_id': route_operation.id,
            'workcenter_id': workcenter.id if workcenter else False,
        })

    def leave_station(self, serial_identity, result, scrap_reason=False,
                      ng_defect=False, operator_code=False):
        """Station mode: an SN leaves its current station.

        result: 'ok' counts as completed and unlocks the successors; 'ng'
        does not, but the SN may re-enter the operation until its retry
        limit (a defect code rides along via ng_defect and is stamped on
        the history row by sn_wsd_quality, which owns the comodel);
        'scrap' is terminal: the board is gone, its components are scrapped
        from the line side through a native scrap order and the SN is
        sealed for this order. Returns True when the SN left through an
        end operation with OK -- its flow on this order is finished."""
        self.ensure_one()
        if result not in ('ok', 'ng', 'scrap'):
            raise ValidationError(_(
                "Leave result must be 'ok', 'ng' or 'scrap'."))
        Wip = self.env['sn.wsd.serial.wip']
        wip = Wip.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ], limit=1)
        if not wip:
            raise ValidationError(_(
                'SN %(sn)s is not in progress on MES order %(order)s.',
                sn=serial_identity.name, order=self.name))
        route_operation = wip.route_operation_id
        if result == 'scrap':
            if not scrap_reason:
                raise ValidationError(_('Select a scrap reason.'))
            self._mes_scrap_components(route_operation, 1.0, scrap_reason)
        if not operator_code:
            employee = self.env.user.employee_id
            operator_code = (
                employee.barcode
                or (employee.user_id.login if employee.user_id else False))
        self.env['sn.wsd.serial.operation.history'].sudo().create(
            self._prepare_leave_history_vals(
                serial_identity, route_operation, wip, result,
                scrap_reason=scrap_reason, ng_defect=ng_defect,
                operator_code=operator_code))
        wip.sudo().unlink()
        # 一扫内核共用出口：T 面单全部流完时自动完结（含 T 面倒冲）
        self._mes_maybe_auto_close()
        return bool(result == 'ok' and route_operation.x_allow_exit)

    def _prepare_leave_history_vals(self, serial_identity, route_operation,
                                    wip, result, scrap_reason=False,
                                    ng_defect=False, operator_code=False):
        """Vals of the append-only history row written on leave. Extended by
        sn_wsd_quality to stamp the NG defect code (the comodel lives there)."""
        return {
            'operator_code': operator_code or False,
            'serial_identity_id': serial_identity.id,
            'mes_order_id': self.id,
            'route_operation_id': route_operation.id,
            'workcenter_id': wip.workcenter_id.id,
            'result': result,
            'in_date': wip.in_date,
            'out_date': fields.Datetime.now(),
        }

    def action_clear_station_pass(self, serial_identity):
        """Clear all station-pass traces of an SN on this order (清除过站).

        Deletes every history row and the WIP row of ``serial_identity`` on
        this order, putting the SN back to "never fed in" (input/output
        counters are stored computes on those rows and recompute by
        themselves). Deliberately touches nothing else: FAI samples, SMT
        points, key-material counts, quality documents and repair gates
        stay as they are. Managers only; one audit row lands in
        ``sn.wsd.clear.pass.log`` (who/when/what). Returns the number of
        deleted history rows."""
        self.ensure_one()
        if isinstance(serial_identity, int):
            serial_identity = self.env['sn.wsd.serial.identity'].browse(
                serial_identity)
        if not self.env.user.has_group('mrp.group_mrp_manager'):
            raise ValidationError(_(
                'Only manufacturing managers can clear station passes.'))
        History = self.env['sn.wsd.serial.operation.history']
        Wip = self.env['sn.wsd.serial.wip']
        history = History.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ])
        wip = Wip.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ])
        if not history and not wip:
            raise ValidationError(_(
                'SN %(sn)s has no station-pass records on MES order '
                '%(order)s.', sn=serial_identity.name, order=self.name))
        cleared_count = len(history)
        history.sudo().unlink()
        wip.sudo().unlink()
        self.env['sn.wsd.clear.pass.log'].sudo().create({
            'mes_order_id': self.id,
            'serial_identity_id': serial_identity.id,
            'cleared_history_count': cleared_count,
            'cleared_wip': bool(wip),
            'company_id': self.company_id.id,
        })
        return cleared_count

    def report_operation_qty(self, route_operation, qty_ok, qty_ng=0.0,
                              qty_scrap=0.0, scrap_reason=False):
        """Report mode: report one batch of an operation.

        报工即开工（report-offline，2026-09-01 用户规则）：报工不要求
        在线/上线；首笔报工把单据转入生产中（领料不可跳过，与上线硬闸
        同口径）。顺序锁为级联制：本工序累计（OK+报废）+ 本批（OK+报废）
        不得超过前置工序累计（OK+报废），多前置（OR-join）取最大；首工序
        只受配额约束。

        Quota rule: this batch (OK + NG + scrap) must fit into the plan
        remainder -- planned minus accumulated OK and scrap. NG is a pure
        statistic (reworked boards come back as a later OK report); scrap
        consumes the quota and generates native scrap orders per BOM
        component from the line side."""
        self.ensure_one()
        if self.x_manage_mode != 'report':
            raise ValidationError(_(
                'MES order %(name)s is managed by SN station tracking; '
                'operation reporting is not available.', name=self.name))
        if qty_ok < 0 or qty_ng < 0 or qty_scrap < 0:
            raise ValidationError(_('Reported quantities cannot be negative.'))
        batch = qty_ok + qty_ng + qty_scrap
        if batch <= 0:
            raise ValidationError(_('Report at least one positive quantity.'))
        if route_operation.mes_route_id != self.x_mes_route_id:
            raise ValidationError(_(
                'Operation %(op)s does not belong to the route of MES order '
                '%(order)s.', op=route_operation.display_label, order=self.name))
        Report = self.env['sn.wsd.mes.operation.report']
        accumulated = sum(
            Report.search([
                ('mes_order_id', '=', self.id),
                ('route_operation_id', '=', route_operation.id),
            ]).mapped(lambda r: r.qty_ok + r.qty_scrap))
        remaining = self.planned_qty - accumulated
        if batch > remaining + 0.0001:
            raise ValidationError(_(
                'Report exceeds the plan remainder: this batch of %(batch)s '
                'would exceed the remaining %(remaining)s of %(planned)s '
                '(NG does not consume quota; scrap and OK do).',
                batch=batch, remaining=max(remaining, 0.0),
                planned=self.planned_qty))
        predecessors = route_operation.blocked_by_ids
        if predecessors:
            def _effective(op):
                reports = op.report_ids
                return sum(reports.mapped(
                    lambda r: r.qty_ok + r.qty_scrap)) if reports else 0.0
            upstream_cap = max(_effective(p) for p in predecessors)
            if accumulated + qty_ok + qty_scrap > upstream_cap + 0.0001:
                raise ValidationError(_(
                    'Operation %(op)s: this report would exceed the '
                    'accumulated quantity of its predecessors (%(cap)s).',
                    op=route_operation.display_label, cap=upstream_cap))
        if self.state in ('released', 'picked'):
            # 首笔报工即开工；领料不可跳过（存在任何未取消领料单即算
            # "领过"，宽松口径防误拦——与 action_online 硬闸一致）
            if not self.picking_ids.filtered(lambda p: p.state != 'cancel'):
                raise ValidationError(_(
                    'MES order %(name)s has no material requisition yet; '
                    'issue material before reporting.', name=self.name))
            self.state = 'in_progress'
        if qty_scrap > 0:
            if not scrap_reason:
                raise ValidationError(_('Select a scrap reason.'))
            self._mes_scrap_components(route_operation, qty_scrap, scrap_reason)
        Report.sudo().create({
            'mes_order_id': self.id,
            'route_operation_id': route_operation.id,
            'qty_ok': qty_ok,
            'qty_ng': qty_ng,
            'qty_scrap': qty_scrap,
        })

    def _mes_scrap_components(self, route_operation, qty_scrap, scrap_reason=False):
        """Scrap the BOM components of qty_scrap boards from the line side
        through native scrap orders (stock.scrap), validated immediately.

        Lot-tracked components are scrapped from the reels this order
        actually scanned online (consumption flows, each lot taking its
        net-flow share) -- never without a lot, which would drive a
        lot-tracked line-side quant negative. Untracked components (screws,
        standard parts) fall back to the BoM ratio; a tracked component
        without consumption flows is a hard stop, mirroring the completion
        backflush."""
        self.ensure_one()
        bom = self.production_id.bom_id
        if not bom or not bom.product_qty:
            raise ValidationError(_(
                'The manufacturing order of MES order %(order)s has no BoM; '
                'scrap cannot be reported without one.', order=self.name))
        line_side = self.production_line_id.workshop_id.component_location_id
        if not line_side:
            raise ValidationError(_(
                'Workshop %(ws)s has no line-side location configured; '
                'cannot scrap components of order %(order)s.',
                ws=self.production_line_id.workshop_id.display_name,
                order=self.name))
        Scrap = self.env['stock.scrap']

        def scrap_vals(product, lot, scrap_qty):
            vals = {
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'scrap_qty': scrap_qty,
                'location_id': line_side.id,
                'origin': self.name,
                'name': _('Operation scrap: %(op)s (%(reason)s)',
                          op=route_operation.display_label,
                          reason=scrap_reason.display_name),
                'x_scrap_reason_id': scrap_reason.id if scrap_reason else False,
                'company_id': self.company_id.id,
            }
            if lot:
                vals['lot_id'] = lot.id
            return vals

        # flow lots per product: the reels this order scanned online
        lots_by_product = {}
        for lot, net_qty in self._mes_flow_net_by_lot().items():
            if net_qty > 0.0001:
                lots_by_product.setdefault(lot.product_id.id, []).append((lot, net_qty))
        covered = set(lots_by_product)
        if covered:
            # BoM lines substituted by a scanned flow product are covered too
            for origin in self.env['product.product'].search([
                ('substitute_ids', 'in', list(covered)),
            ]):
                covered.add(origin.id)

        per_board = qty_scrap / bom.product_qty
        # 按面别过滤：报废同一张 BOM 但只扣本面的行（单面单=single 行）
        scrap_side_lines = bom.bom_line_ids
        if self.x_side:
            scrap_side_lines = scrap_side_lines.filtered(
                lambda l: l.x_board_side == self.x_side)
        for line in scrap_side_lines:
            need = line.product_qty * per_board
            if need <= 0.0001:
                continue
            if line.product_id.id in covered:
                total_net = sum(
                    net for _, net in lots_by_product[line.product_id.id])
                for lot, net_qty in lots_by_product[line.product_id.id]:
                    scrap_qty = need * net_qty / total_net
                    if scrap_qty <= 0.0001:
                        continue
                    Scrap.sudo().create(
                        scrap_vals(line.product_id, lot, scrap_qty)
                    ).do_scrap()
                continue
            if line.product_id.tracking != 'none':
                raise ValidationError(_(
                    'Component %(product)s of MES order %(order)s is lot/'
                    'serial tracked but has no consumption flows: load the '
                    'material and pass the stations first, or review the BOM.',
                    product=line.product_id.display_name, order=self.name))
            Scrap.sudo().create(
                scrap_vals(line.product_id, False, need)
            ).do_scrap()

    # ------------------------------------------------------------------
    # state transitions
    # ------------------------------------------------------------------
    def action_cancel(self):
        """Revoke (撤排) -- 架构设计 3.2:

        1. only ``released`` orders can be cancelled;
        2. any done (already issued) picking forbids cancellation -- unless
           the ``mes_force_cancel`` context is set (MO force close), where
           issued batches stay on the books and the order is revoked anyway;
        3. pickings that were generated but not issued are cancelled along
           with the order, so the warehouse can no longer issue them;
        4. the MO scheduling figures fall back automatically (F1 compute).
        """
        force = self.env.context.get('mes_force_cancel')
        blocked = self.filtered(lambda o: o.state != 'released')
        if blocked:
            raise ValidationError(_(
                'Only Released MES orders can be cancelled. Blocked: %s',
                ', '.join(blocked.mapped('name')),
            ))
        issued = self.picking_ids.filtered(lambda p: p.state == 'done')
        if issued and not force:
            raise ValidationError(_(
                'Material has already been issued for MES order(s) %(orders)s '
                '(%(pickings)s); cancellation is forbidden.',
                orders=', '.join(issued.mapped('x_mes_order_id.name')),
                pickings=', '.join(issued.mapped('display_name')),
            ))
        open_pickings = self.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))
        if open_pickings:
            open_pickings.action_cancel()
        self.write({'state': 'cancelled'})

    def _update_pick_state(self):
        """Single point for the released -> picked transition (架构设计 3.3).

        ``picked`` means: the accumulated picked quantity reaches the order
        quantity AND every non-cancelled picking is done. Kept in one method
        on purpose -- if the business rule changes, only this changes.
        Defensive: never touches orders that are not still ``released`` (e.g.
        a cancelled order with a leftover done picking).
        """
        for order in self:
            if order.state != 'released':
                continue
            pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
            if pickings and all(p.state == 'done' for p in pickings) \
                    and order.picked_qty + 0.0001 >= order.planned_qty:
                order.state = 'picked'

    def _on_done(self):
        """Close the MO once every MES order is done (架构设计 3.5).

        The MES documents (requisitions, backflush moves, completion
        receipts) supersede the MO's own moves, so those are cancelled and
        the MO is marked done instead of running the native completion."""
        for order in self:
            mo = order.production_id
            if not (mo.x_mes_order_ids and all(o.state == 'done' for o in mo.x_mes_order_ids)):
                continue
            (mo.move_raw_ids | mo.move_finished_ids).filtered(
                lambda m: m.state not in ('done', 'cancel'))._action_cancel()
            mo.write({'state': 'done'})

    # ------------------------------------------------------------------
    # completion (完工入库): backflush + receipt + state/MO closure
    # ------------------------------------------------------------------
    def _mes_production_location(self):
        """Virtual production location used as the source of receipts and
        the destination of backflush consumption."""
        self.ensure_one()
        mo = self.production_id
        if mo.move_raw_ids:
            return mo.move_raw_ids[:1].location_dest_id
        return self.env['stock.location'].search([
            ('usage', '=', 'production'),
            ('company_id', 'in', [self.company_id.id, False]),
        ], limit=1)

    def _mes_flow_net_by_lot(self):
        """消耗流水净值钩子（按卷）：SMT 扣点与整机关键物料 usage_times
        流水在 sn_wsd_smt 覆写本方法；未装该模块时无流水，完工倒冲退回
        纯 BOM 口径。"""
        self.ensure_one()
        return {}

    def _mes_backflush(self, qty, flow_ratio=False, move_label=None):
        """Consume materials x qty from the line side (no document,
        manufacturing-consumption style). Fails hard on line-side
        shortage -- the whole completion rolls back.

        有消耗流水的组件按 卷×净值×本次完工比例 带批次扣减——扣的是
        上线扫描的那个物料SN（含 BOM 没有的替代料/关键物料）；被流水
        产品替代的 BOM 行不再重复扣；其余组件维持 BOM×比例。

        ``flow_ratio``：流水缩放比例，默认 本次数量÷产出数量（完工入
        库口径）。T 面单完结（不入库）传 (过点板数−报废板数)÷过点板数
        ——报废板的份额已由报废单扣过，不再重复扣。"""
        self.ensure_one()
        bom = self.production_id.bom_id
        if not bom or not bom.product_qty:
            raise ValidationError(_(
                'The manufacturing order of MES order %(order)s has no BoM; '
                'products cannot be completed without one.',
                order=self.name))
        line_side = self.production_line_id.workshop_id.component_location_id
        if not line_side:
            raise ValidationError(_(
                'Workshop %(ws)s has no line-side location configured; '
                'cannot backflush components of order %(order)s.',
                ws=self.production_line_id.workshop_id.display_name,
                order=self.name))
        production_loc = self._mes_production_location()
        StockMove = self.env['stock.move']
        moves = StockMove

        def line_side_available(product, lot=False):
            domain = [
                ('product_id', '=', product.id),
                ('location_id', '=', line_side.id),
                ('quantity', '>', 0),
            ]
            if lot:
                domain.append(('lot_id', '=', lot.id))
            groups = self.env['stock.quant']._read_group(
                domain, groupby=[], aggregates=['quantity:sum'])
            return (groups[0][0] or 0.0) if groups else 0.0

        def ensure_available(product, need, lot=False):
            """线边可用性硬校验（docstring 承诺的 fails hard）：任何组件
            线边不够扣，整个完工回滚——半成品/上游料未入库未领料时，
            下游单不允许静默扣成负库存。"""
            available = line_side_available(product, lot=lot)
            if available + 0.0001 < need:
                raise ValidationError(_(
                    'Line-side stock of %(product)s%(lot)s is insufficient to '
                    'complete MES order %(order)s: need %(need)s, available '
                    '%(available)s. Issue the material first (领料) or '
                    'validate the upstream receipt (半成品入库).',
                    product=product.display_name,
                    lot=' [%s]' % lot.name if lot else '',
                    order=self.name, need=need, available=available))

        net_by_lot = self._mes_flow_net_by_lot()
        flow_product_ids = set()
        if net_by_lot:
            if flow_ratio is False:
                output_qty = self.x_output_qty or 0.0
                if output_qty <= 0:
                    raise ValidationError(_(
                        'MES order %(order)s has consumption flows but no output '
                        'quantity; cannot scale the backflush to %(qty)s units.',
                        order=self.name, qty=qty))
                flow_ratio = qty / output_qty
            for lot, net_qty in net_by_lot.items():
                consume_qty = net_qty * flow_ratio
                if consume_qty <= 0.0001:
                    continue
                ensure_available(lot.product_id, consume_qty, lot=lot)
                flow_product_ids.add(lot.product_id.id)
                moves |= StockMove.create({
                    'description_picking_manual': move_label or _('MES completion %(order)s', order=self.name),
                    'product_id': lot.product_id.id,
                    'product_uom': lot.product_id.uom_id.id,
                    'product_uom_qty': consume_qty,
                    'picked': True,
                    'location_id': line_side.id,
                    'location_dest_id': production_loc.id,
                    'company_id': self.company_id.id,
                    'origin': self.name,
                    'move_line_ids': [(0, 0, {
                        'product_id': lot.product_id.id,
                        'product_uom_id': lot.product_id.uom_id.id,
                        'quantity': consume_qty,
                        'lot_id': lot.id,
                        'lot_name': lot.name,
                        'location_id': line_side.id,
                        'location_dest_id': production_loc.id,
                        'company_id': self.company_id.id,
                        'picked': True,
                    })],
                })
            # 被流水产品替代的 BOM 产品不再按 BOM 扣（已被替代上线）
            for origin in self.env['product.product'].search([
                ('substitute_ids', 'in', list(flow_product_ids)),
            ]):
                flow_product_ids.add(origin.id)

        bom_ratio = qty / bom.product_qty
        # 按面别过滤：BOM 兜底散料只扣本面的行（单面单=single 行）
        backflush_side_lines = bom.bom_line_ids
        if self.x_side:
            backflush_side_lines = backflush_side_lines.filtered(
                lambda l: l.x_board_side == self.x_side)
        for line in backflush_side_lines:
            if line.product_id.id in flow_product_ids:
                continue
            consume_qty = line.product_qty * bom_ratio
            if consume_qty <= 0.0001:
                continue
            # BOM 兜底只服务无批次的散料（螺丝/标准件）。批次料必须走
            # 上料/过站流水回填：出现在这里说明本单没有该料的消耗流水
            # （没上料就完工），硬拦而不是盲扣
            if line.product_id.tracking != 'none':
                raise ValidationError(_(
                    'Component %(product)s of MES order %(order)s is lot/'
                    'serial tracked but has no consumption flows: complete '
                    'loading and station passes first, or review the BOM.',
                    product=line.product_id.display_name, order=self.name))
            ensure_available(line.product_id, consume_qty)
            moves |= StockMove.create({
                'description_picking_manual': move_label or _('MES completion %(order)s', order=self.name),
                'product_id': line.product_id.id,
                'product_uom': line.product_uom_id.id,
                'product_uom_qty': consume_qty,
                'quantity': consume_qty,
                'picked': True,
                'location_id': line_side.id,
                'location_dest_id': production_loc.id,
                'company_id': self.company_id.id,
                'origin': self.name,
            })
        if moves:
            moves._action_done()
        return moves


    def _mes_receipt_picking_type(self, warehouse):
        """Dedicated per-warehouse completion receipt operation type,
        created on first use (same pattern as material issue)."""
        self.ensure_one()
        if warehouse.picking_type_receipt_id:
            return warehouse.picking_type_receipt_id
        seq = self.env['ir.sequence'].sudo().create({
            'name': _('Finished Goods Receipt') + ': ' + warehouse.name,
            'code': 'sn.wsd.mes.picking.receipt',
            'prefix': (warehouse.code or 'WH') + '/FR/',
            'padding': 4,
            'company_id': warehouse.company_id.id,
        })
        picking_type = self.env['stock.picking.type'].create({
            'name': _('Finished Goods Receipt'),
            'code': 'internal',
            'sequence_code': 'sn.wsd.mes.picking.receipt',
            'sequence_id': seq.id,
            'warehouse_id': warehouse.id,
            'company_id': warehouse.company_id.id,
        })
        warehouse.picking_type_receipt_id = picking_type.id
        return picking_type

    def _mes_return_picking_type(self, warehouse):
        """Dedicated per-warehouse material return operation type
        (WH/MR)，created on first use (same pattern as material issue).
        退料与领料分型：仓库按作业类型区分单据与报表。"""
        self.ensure_one()
        if warehouse.picking_type_return_id:
            return warehouse.picking_type_return_id
        seq = self.env['ir.sequence'].sudo().create({
            'name': _('Material Return') + ': ' + warehouse.name,
            'code': 'sn.wsd.mes.picking.return',
            'prefix': (warehouse.code or 'WH') + '/MR/',
            'padding': 4,
            'company_id': warehouse.company_id.id,
        })
        picking_type = self.env['stock.picking.type'].create({
            'name': _('Material Return'),
            'code': 'internal',
            'sequence_code': 'sn.wsd.mes.picking.return',
            'sequence_id': seq.id,
            'warehouse_id': warehouse.id,
            'company_id': warehouse.company_id.id,
        })
        # 类型名是可翻译字段：懒创建只落创建者语言，这里按 po 给
        # zh_CN 也写一份，避免中文界面看到英文类型名（源码仍全英文）
        zh_name = self.with_context(lang='zh_CN').env._('Material Return')
        if zh_name != 'Material Return':
            picking_type.with_context(lang='zh_CN').name = zh_name
        warehouse.picking_type_return_id = picking_type.id
        return picking_type

    def _mes_over_pick_picking_type(self, warehouse):
        """Dedicated per-warehouse over-pick operation type (WH/OP)，
        created on first use. 超领（补料）与账内领料分型。"""
        self.ensure_one()
        if warehouse.picking_type_over_pick_id:
            return warehouse.picking_type_over_pick_id
        seq = self.env['ir.sequence'].sudo().create({
            'name': _('Material Over-pick') + ': ' + warehouse.name,
            'code': 'sn.wsd.mes.picking.over',
            'prefix': (warehouse.code or 'WH') + '/OP/',
            'padding': 4,
            'company_id': warehouse.company_id.id,
        })
        picking_type = self.env['stock.picking.type'].create({
            'name': _('Material Over-pick'),
            'code': 'internal',
            'sequence_code': 'sn.wsd.mes.picking.over',
            'sequence_id': seq.id,
            'warehouse_id': warehouse.id,
            'company_id': warehouse.company_id.id,
        })
        # 类型名是可翻译字段：懒创建只落创建者语言，这里按 po 给
        # zh_CN 也写一份，避免中文界面看到英文类型名（源码仍全英文）
        zh_name = self.with_context(lang='zh_CN').env._('Material Over-pick')
        if zh_name != 'Material Over-pick':
            picking_type.with_context(lang='zh_CN').name = zh_name
        warehouse.picking_type_over_pick_id = picking_type.id
        return picking_type

    def _mes_create_receipt(self, qty, destination, workshop=False, lot_name=False):
        """One completion receipt: production -> finished-goods stock
        (waiting for warehouse validation) or -> workshop line side
        (auto-validated). 成品 tracking='lot' 时收货行挂批次：批次来自
        调用方（向导输入），留空按 制令单+日期 自动生成/复用。"""
        self.ensure_one()
        mo = self.production_id
        warehouse = mo.picking_type_id.warehouse_id
        if not warehouse:
            raise ValidationError(_(
                'The manufacturing order of %(order)s has no warehouse; '
                'cannot create the completion receipt.', order=self.name))
        if destination == 'lineside':
            if not workshop or not workshop.component_location_id:
                raise ValidationError(_(
                    'Select a workshop with a configured line-side location '
                    'for a line-side completion.'))
            if workshop.component_location_id.warehouse_id != warehouse:
                raise ValidationError(_(
                    'Workshop %(ws)s does not belong to the warehouse of MES '
                    'order %(order)s.', ws=workshop.display_name,
                    order=self.name))
            dest = workshop.component_location_id
        else:
            dest = mo.location_dest_id
        src = self._mes_production_location()
        picking_type = self._mes_receipt_picking_type(warehouse)
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': self.name,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'company_id': self.company_id.id,
            'x_mes_order_id': self.id,
            'x_mes_order_qty': qty,
        })
        lot = False
        if mo.product_id.tracking == 'lot':
            lot_value = (lot_name or '').strip() or '%s-%s' % (
                self.name, fields.Date.context_today(self).strftime('%Y%m%d'))
            lot = self.env['stock.lot'].search([
                ('name', '=', lot_value),
                ('product_id', '=', mo.product_id.id),
                ('company_id', 'in', [self.company_id.id, False]),
            ], limit=1)
            if not lot:
                lot = self.env['stock.lot'].create({
                    'name': lot_value,
                    'product_id': mo.product_id.id,
                    'company_id': self.company_id.id,
                })
        move_vals = {
            'description_picking_manual': _('MES completion %(order)s', order=self.name),
            'product_id': mo.product_id.id,
            'product_uom': mo.product_uom_id.id,
            'product_uom_qty': qty,
            'quantity': qty,
            'picked': True,
            'picking_id': picking.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'company_id': self.company_id.id,
        }
        if lot:
            # 批次挂到收货行（quantity 由行汇总），仓库验证/自动验证都不再缺批次
            move_vals.pop('quantity', None)
            move_vals['move_line_ids'] = [(0, 0, {
                'product_id': mo.product_id.id,
                'product_uom_id': mo.product_uom_id.id,
                'quantity': qty,
                'lot_id': lot.id,
                'lot_name': lot.name,
                'location_id': src.id,
                'location_dest_id': dest.id,
                'company_id': self.company_id.id,
                'picked': True,
            })]
        self.env['stock.move'].create(move_vals)
        picking.action_confirm()
        if destination == 'lineside':
            picking.button_validate()
        return picking

    def _mes_create_pallet_receipt(self, qty, cartons, origin_pallets=False):
        """Pallet receipt with per-carton move lines: production ->
        finished stock, each carton ends up as its own package at the
        destination location."""
        self.ensure_one()
        mo = self.production_id
        warehouse = mo.picking_type_id.warehouse_id
        if not warehouse:
            raise ValidationError(_(
                'The manufacturing order of %(order)s has no warehouse; '
                'cannot create the completion receipt.', order=self.name))
        src = self._mes_production_location()
        dest = mo.location_dest_id
        picking_type = self._mes_receipt_picking_type(warehouse)
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': self.name if not origin_pallets else '%s (%s)' % (self.name, origin_pallets),
            'location_id': src.id,
            'location_dest_id': dest.id,
            'company_id': self.company_id.id,
            'x_mes_order_id': self.id,
            'x_mes_order_qty': qty,
        })
        # 不设 quantity/picked —— 设了会触发 _set_quantity inverse 自动创建
        # move line 并传播 description_picking_manual（line 上无此字段），改为
        # 下方手动创建带箱结构的 move line 并回写数量
        move = self.env['stock.move'].create({
            'product_id': mo.product_id.id,
            'product_uom': mo.product_uom_id.id,
            'product_uom_qty': qty,
            'picking_id': picking.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'company_id': self.company_id.id,
        })
        # 每箱一条 move line（本系统包装体系为自建 stock.package，
        # 与库存原生 package 无关联，箱号记入 picking 的 origin 注记）
        for carton in cartons:
            meters = len(carton.x_meter_pack_record_ids)
            if not meters:
                continue
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': mo.product_id.id,
                'product_uom_id': mo.product_uom_id.id,
                'quantity': meters,
                'quantity_product_uom': meters,
                'location_id': src.id,
                'location_dest_id': dest.id,
                'company_id': self.company_id.id,
            })
        # quantity 是 computed-stored（Σ move lines），不手写——写它会触发
        # _set_quantity inverse 再创建 move line 并传播 description_picking_manual
        picking.action_confirm()
        return picking

    def action_close(self, auto=False):
        """Close a dual-sided non-final MES order (T-side): backflush this
        order's own components, then mark done without any stock receipt.
        The physical boards stay on the line and continue on the paired
        B-side order.

        扣料优先级与完工入库同源（_mes_backflush）：有消耗流水的按流
        水净值扣（料站表扣点 + 关键物料），没上的按 BOM 本面行兜底。"""
        for order in self:
            if order.state == 'done':
                raise ValidationError(_(
                    'MES order %(name)s is already done.', name=order.name))
            if order.state == 'cancelled':
                raise ValidationError(_(
                    'MES order %(name)s is cancelled.', name=order.name))
            if not order.x_is_dual_side_non_final:
                raise ValidationError(_(
                    'MES order %(name)s is not a dual-sided non-final (T-side) '
                    'order; use Complete Receipt instead.', name=order.name))
            moves = order._mes_close_backflush()
            order.write({
                'state': 'done',
                'x_done_qty': order.x_output_qty,
                'x_done_date': fields.Datetime.now(),
            })
            order._on_done()
            order.message_post(body=_(
                'Closed without receipt%(auto)s: %(boards)s board(s) finished '
                'the T-side route; %(moves)s component move(s) backflushed '
                'from the line side.',
                auto=_(' (automatic)') if auto else '',
                boards=order.x_output_qty or 0.0,
                moves=len(moves)))
        return True

    def _mes_close_backflush(self):
        """T 面单完结时的自身倒冲：份额 = (过点板数 − 本单报废板数)。

        过点板数 = 有消耗流水的板（贴片扣点/关键物料都算）；报废板的
        份额已由报废单扣过，从比例里剔除；完全没有流水的单退回
        BOM×产出 散料口径。"""
        self.ensure_one()
        passed_ids = set()
        if 'sn.smt.material.consumption' in self.env:
            passed_ids = set(self.env['sn.smt.material.consumption'].search([
                ('mes_order_id', '=', self.id),
                ('product_qty', '>', 0),
            ]).mapped('serial_identity_id').ids)
        scrapped_ids = set(self.sn_history_ids.filtered(
            lambda h: h.result == 'scrap').mapped('serial_identity_id').ids)
        billable = len(passed_ids - scrapped_ids)
        if billable <= 0:
            # 无流水的纯散料单：按产出板数走 BOM 兜底
            billable = int(self.x_output_qty or 0)
        if billable <= 0:
            return self.env['stock.move']
        ratio = (len(passed_ids) - len(passed_ids & scrapped_ids)) / len(passed_ids) \
            if passed_ids else False
        return self._mes_backflush(
            billable, flow_ratio=ratio,
            move_label=_('MES close without receipt %(order)s', order=self.name))

    def _mes_maybe_auto_close(self):
        """自动关结（架构约定：T 面全部流完 → 单据自动完结，少一步人工）。

        触发条件（过站内核 leave_station 每次调用后判定）：
        1. 双面产品的 T 面单，且仍处于生产中；
        2. 产出 OK 数 + 本单报废数 ≥ 排产数量（没投满不自动关，按钮兜底）；
        3. 线上无在制 WIP（有板在修/未流出则等）。
        满足即走 action_close（含 T 面倒冲）。"""
        for order in self:
            if not order.x_is_dual_side_non_final or order.state != 'in_progress':
                continue
            if order.sn_wip_ids:
                continue
            scrapped = len(set(order.sn_history_ids.filtered(
                lambda h: h.result == 'scrap').mapped('serial_identity_id').ids))
            planned = order.planned_qty or 0.0
            if planned <= 0:
                continue
            if (order.x_output_qty or 0.0) + scrapped + 0.0001 < planned:
                continue
            order.action_close(auto=True)

    def action_complete(self, qty, destination='stock', workshop=False, lot_name=False):
        """Complete (完工入库) -- the single execution entry used by both
        the form wizard and the shop-floor terminal.

        1. backflush components from the line side (fails on shortage)
        2. create the completion receipt (auto-validated for line side)
        3. accumulate the done quantity; close the order and the MO when
           the output quantity is fully received

        ``lot_name``：成品批次（tracking='lot' 时），向导可填；留空按
        制令单+日期自动生成，车间终端等无输入入口走自动生成。"""
        self.ensure_one()
        # 产出不要求在线（与 action_offline 语义一致）：下线只是停止投入
        # 新 SN，在制产出与完工入库照常进行；只要求单据处于生产中
        if self.state != 'in_progress':
            raise ValidationError(_(
                'MES order %(name)s must be in progress to '
                'complete products.', name=self.name))
        if qty <= 0:
            raise ValidationError(_('The completion quantity must be positive.'))
        self._mes_backflush(qty)
        self._mes_create_receipt(qty, destination, workshop=workshop, lot_name=lot_name)
        self.write({
            'x_done_qty': self.x_done_qty + qty,
            'x_done_date': fields.Datetime.now(),
        })
        if self.x_done_qty + 0.0001 >= self.x_output_qty:
            self.state = 'done'
            self._on_done()
        return True

    def action_open_done_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Complete Products'),
            'res_model': 'sn.wsd.mes.done.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_mes_order_id': self.id},
        }

    # ------------------------------------------------------------------
    # F5: material picking (领料) -- warehouse -> workshop line-side staging.
    # Route X: a plain internal transfer; procurement was handled at MO level
    # (F4), this only physically moves the prepared material to the line side.
    # ------------------------------------------------------------------
    def action_open_pick_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pick Material'),
            'res_model': 'sn.wsd.mes.pick.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_mes_order_id': self.id},
        }

    def action_generate_picking(self, qty_this=None, over_reason=False):
        """Generate one internal picking for ``qty_this`` finished units.

        ``qty_this`` is the batch quantity of this issue (架构设计 3.3); it
        defaults to whatever remains of the order quantity. The accumulated
        ``picked_qty`` may never exceed the order quantity — unless
        ``over_reason`` is given: then the picking is an over-pick (beyond
        the plan, separate ledger, no caps).
        """
        StockMove = self.env['stock.move']
        StockPicking = self.env['stock.picking']
        PickingType = self.env['stock.picking.type']
        for order in self.filtered(
                lambda o: o.state in ('released', 'picked', 'in_progress')):
            if qty_this is None:
                qty_this = order.planned_qty - order.picked_qty
            if qty_this <= 0.0001:
                raise UserError(_(
                    'Nothing left to pick on MES order %(order)s.', order=order.name))
            if not over_reason and qty_this + order.picked_qty > order.planned_qty + 0.0001:
                raise UserError(_(
                    'Over-picking: %(qty)s units would exceed the %(planned)s units '
                    'of %(order)s (already picked: %(picked)s).',
                    qty=qty_this, planned=order.planned_qty,
                    order=order.name, picked=order.picked_qty))
            production = order.production_id
            bom = production.bom_id
            if not bom:
                raise UserError(_('No BOM on the manufacturing order; cannot generate the requisition.'))
            line_side = order.production_line_id.workshop_id.component_location_id
            if not line_side:
                raise UserError(_(
                    'Workshop %(workshop)s has no component (line-side) location configured; '
                    'set it before generating the requisition.',
                    workshop=order.production_line_id.workshop_id.display_name,
                ))
            # Route X: the requisition always ships from the warehouse main
            # stock to the line-side location. The MO itself consumes FROM
            # the line-side location, so the two flows never overlap.
            warehouse = production.picking_type_id.warehouse_id
            if not warehouse:
                raise UserError(_(
                    'The manufacturing order of %(order)s has no warehouse; '
                    'cannot generate the requisition.', order=order.name))
            src = warehouse.lot_stock_id
            if not src or src == line_side:
                raise UserError(_(
                    'The workshop line-side location must differ from the '
                    'warehouse stock location.'
                ))
            # dedicated operation types per warehouse: never guess from
            # code='internal' (Quality Control shares that code and used to
            # get picked by accident). Over-picks carry their own WH/OP type
            # so the warehouse can tell issues and supplements apart.
            if over_reason:
                picking_type = order._mes_over_pick_picking_type(warehouse)
            else:
                picking_type = warehouse.picking_type_issue_id
            if not picking_type:
                seq = self.env['ir.sequence'].sudo().create({
                    'name': _('Material Issue') + ': ' + warehouse.name,
                    'code': 'sn.wsd.mes.picking.issue',
                    'prefix': (warehouse.code or 'WH') + '/MI/',
                    'padding': 4,
                    'company_id': warehouse.company_id.id,
                })
                picking_type = PickingType.create({
                    'name': _('Material Issue'),
                    'code': 'internal',
                    'sequence_code': 'sn.wsd.mes.picking.issue',
                    'sequence_id': seq.id,
                    'warehouse_id': warehouse.id,
                    'company_id': warehouse.company_id.id,
                    'default_location_src_id': src.id,
                    'default_location_dest_id': line_side.id,
                })
                warehouse.picking_type_issue_id = picking_type.id
            # this batch's share of the BOM, in BOM-line UoM, capped by what
            # is still open on the whole order (open + done pickings count,
            # so the accumulated issue can never exceed the order scope)
            batch_ratio = (qty_this / bom.product_qty) if bom.product_qty else 0.0
            total_ratio = (order.planned_qty / bom.product_qty) if bom.product_qty else 0.0
            open_pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
            # 覆盖即止预检：整卷发放后（发 995 覆盖需求 3），后续领料的
            # 组件全部被 already 封顶跳过——此时不建空领料单
            def _issue_qty_for(line):
                batch_qty = line.product_qty * batch_ratio
                already = order._mes_issued_qty(line.product_id, open_pickings)
                remaining_total = line.product_qty * total_ratio - already
                return min(batch_qty, remaining_total)
            if not over_reason and all(
                _issue_qty_for(line) <= 0.0001
                for line in bom.bom_line_ids
                if not line.x_advance_issue
            ):
                raise UserError(_(
                    'All components of MES order %(order)s are already covered '
                    'by issued reels; nothing to pick.', order=order.name))
            picking = StockPicking.create({
                'picking_type_id': picking_type.id,
                'origin': order.name,
                'location_id': src.id,
                'location_dest_id': line_side.id,
                'company_id': order.company_id.id,
                'x_mes_order_id': order.id,
                'x_mes_order_qty': qty_this,
                'x_is_over_pick': bool(over_reason),
                'x_over_reason': over_reason or False,
            })
            # 按面别过滤 BOM 行：领料只领本面的行（单面单=single 行）
            side_lines = bom.bom_line_ids
            if order.x_side:
                side_lines = side_lines.filtered(
                    lambda l: l.x_board_side == order.x_side)
            for line in side_lines:
                if line.x_advance_issue:
                    continue  # pre-issued to the line side, never on MES pickings
                batch_qty = line.product_qty * batch_ratio
                already = order._mes_issued_qty(line.product_id, open_pickings)
                remaining_total = line.product_qty * total_ratio - already
                # 超领走账外：不占 BOM 行总封顶，按超领台数整份展开
                qty = batch_qty if over_reason else min(batch_qty, remaining_total)
                if qty <= 0.0001:
                    continue  # nothing left to issue for this component
                move_vals = {
                    'product_id': line.product_id.id,
                    'product_uom': line.product_uom_id.id,
                    'product_uom_qty': qty,
                    'picking_id': picking.id,
                    'location_id': src.id,
                    'location_dest_id': line_side.id,
                    'company_id': order.company_id.id,
                }
                # 整卷发放（2026-08-27 方案）：批次料剪不开——出入库扫物料SN、
                # 数量=卷当前余量。BOM 需求只作覆盖门槛（够一卷发一卷），
                # 行按 FEFO 挑卷，一卷一行；台数顶与 already 封顶不受影响
                # （累计 1000 ≥ 需求 200 → 本单后续领料自动跳过该料）。
                if line.product_id.tracking == 'lot':
                    need_base = line.product_uom_id._compute_quantity(
                        qty, line.product_id.uom_id)
                    reels = order._mes_issue_reel_lines(
                        line.product_id, src, need_base)
                    if reels:
                        move_vals['product_uom_qty'] = line.product_id.uom_id._compute_quantity(
                            sum(reel_qty for _lot, reel_qty in reels),
                            line.product_uom_id)
                        move_vals['move_line_ids'] = [(0, 0, {
                            'picking_id': picking.id,
                            'product_id': line.product_id.id,
                            'product_uom_id': line.product_id.uom_id.id,
                            'quantity': reel_qty,
                            'lot_id': lot.id,
                            'lot_name': lot.name,
                            'location_id': src.id,
                            'location_dest_id': line_side.id,
                            'company_id': order.company_id.id,
                        }) for lot, reel_qty in reels]
                StockMove.create(move_vals)
            picking.action_confirm()
        return True

    def _mes_issued_qty(self, product, pickings):
        """BOM 行累计已发量（物理口径，open+done 单据均计）。退货单
        （负台数）按负方向参与——退料回补额度，而不是被当作又一次发放
        （mes-picking-lifecycle R2）。"""
        self.ensure_one()
        issued = 0.0
        for picking in pickings:
            sign = -1.0 if picking.x_mes_order_qty < 0 else 1.0
            for move in picking.move_ids.filtered(lambda m: m.product_id == product):
                issued += sign * move.product_uom_qty
        return issued

    def action_open_return_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return Material'),
            'res_model': 'sn.wsd.mes.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_mes_order_id': self.id},
        }

    def action_generate_return(self, qty=None):
        """生成一张反向领料单：按 ``qty`` 台的 BOM 份额把组件从线边退回
        仓库主库位。单据 ``x_mes_order_qty`` 记负数（净额账本约定），
        批次料按线边在库批次整卷退（FEFO，一卷一行），散料数量上限为
        线边实际持有量。"""
        StockMove = self.env['stock.move']
        StockPicking = self.env['stock.picking']
        StockQuant = self.env['stock.quant']
        for order in self:
            if qty is None:
                qty = order.picked_qty
            if qty <= 0.0001:
                raise UserError(_(
                    'Nothing picked to return on MES order %(order)s.',
                    order=order.name))
            if qty > order.picked_qty + 0.0001:
                raise UserError(_(
                    'Over-return: %(qty)s units exceed the %(net)s net picked '
                    'units of %(order)s.',
                    qty=qty, net=order.picked_qty, order=order.name))
            production = order.production_id
            bom = production.bom_id
            if not bom:
                raise UserError(_(
                    'No BOM on the manufacturing order; cannot generate '
                    'the return.'))
            line_side = order.production_line_id.workshop_id.component_location_id
            if not line_side:
                raise UserError(_(
                    'Workshop %(workshop)s has no component (line-side) '
                    'location configured; set it before generating the return.',
                    workshop=order.production_line_id.workshop_id.display_name,
                ))
            warehouse = production.picking_type_id.warehouse_id
            if not warehouse or not warehouse.lot_stock_id:
                raise UserError(_(
                    'The manufacturing order of %(order)s has no warehouse; '
                    'cannot generate the return.', order=order.name))
            dest = warehouse.lot_stock_id
            picking_type = order._mes_return_picking_type(warehouse)
            batch_ratio = (qty / bom.product_qty) if bom.product_qty else 0.0
            picking = StockPicking.create({
                'picking_type_id': picking_type.id,
                'origin': order.name,
                'location_id': line_side.id,
                'location_dest_id': dest.id,
                'company_id': order.company_id.id,
                'x_mes_order_id': order.id,
                'x_mes_order_qty': -qty,
            })
            created_any = False
            for line in bom.bom_line_ids:
                if line.x_advance_issue:
                    continue  # pre-issued lines never flow through MES pickings
                qty_line = line.product_qty * batch_ratio
                if qty_line <= 0.0001:
                    continue
                move_vals = {
                    'product_id': line.product_id.id,
                    'product_uom': line.product_uom_id.id,
                    'product_uom_qty': qty_line,
                    'picking_id': picking.id,
                    'location_id': line_side.id,
                    'location_dest_id': dest.id,
                    'company_id': order.company_id.id,
                }
                if line.product_id.tracking == 'lot':
                    # 整卷退：线边在库批次按 FEFO 覆盖份额即止，一卷一行；
                    # 线边无该批次（已消耗）则该行不退
                    need_base = line.product_uom_id._compute_quantity(
                        qty_line, line.product_id.uom_id)
                    reels = order._mes_issue_reel_lines(
                        line.product_id, line_side, need_base)
                    if not reels:
                        continue
                    move_vals['product_uom_qty'] = line.product_id.uom_id._compute_quantity(
                        sum(reel_qty for _lot, reel_qty in reels),
                        line.product_uom_id)
                    move_vals['move_line_ids'] = [(0, 0, {
                        'picking_id': picking.id,
                        'product_id': line.product_id.id,
                        'product_uom_id': line.product_id.uom_id.id,
                        'quantity': reel_qty,
                        'lot_id': lot.id,
                        'lot_name': lot.name,
                        'location_id': line_side.id,
                        'location_dest_id': dest.id,
                        'company_id': order.company_id.id,
                    }) for lot, reel_qty in reels]
                else:
                    # 散料按线边实际持有量封顶（倒冲扣过的退不回来）
                    groups = StockQuant._read_group(
                        [('product_id', '=', line.product_id.id),
                         ('location_id', '=', line_side.id)],
                        groupby=[], aggregates=['quantity:sum'],
                    )
                    available_base = (groups[0][0] or 0.0) if groups else 0.0
                    available = line.product_id.uom_id._compute_quantity(
                        available_base, line.product_uom_id)
                    qty_line = min(qty_line, available)
                    if qty_line <= 0.0001:
                        continue
                    move_vals['product_uom_qty'] = qty_line
                StockMove.create(move_vals)
                created_any = True
            if not created_any:
                picking.action_cancel()
                raise UserError(_(
                    'No component of MES order %(order)s is left on the line '
                    'side to return.', order=order.name))
            picking.action_confirm()
        return True

    def _mes_issue_reel_lines(self, product, src, need_qty):
        """整卷发放的挑卷：按 FEFO（先到期，再先进）取 ``src`` 库位在库
        批次的**当前余量**，累计覆盖 ``need_qty``（产品基本单位）即止。
        在途互斥（mes-picking-lifecycle R4）：同制令单未验证领料单已挑
        走的批次量先从在库量中扣减，避免两张在途单挑中同一卷。
        返回 [(lot, qty)]；无可发批次时返回空（回退散量领料）。"""
        self.ensure_one()
        need = product.uom_id.round(need_qty or 0.0)
        if need <= 0:
            return []
        groups = self.env['stock.quant']._read_group(
            [
                ('product_id', '=', product.id),
                ('location_id', '=', src.id),
                ('lot_id', '!=', False),
                ('quantity', '>', 0),
            ],
            groupby=['lot_id'],
            aggregates=['quantity:sum'],
        )
        by_lot = {lot: (total or 0.0) for lot, total in groups}
        # 同单在途占用：未验证领料单上挂在 src 的批次行（退货单的行在
        # 线边，location 不同，天然不参与）
        open_pickings = self.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))
        for picking in open_pickings:
            for line in picking.move_line_ids.filtered(
                    lambda l: l.product_id == product
                    and l.lot_id and l.location_id == src):
                if line.lot_id.id in {lot.id for lot in by_lot}:
                    by_lot[line.lot_id] -= line.quantity
        lines = []
        covered = 0.0
        for lot in sorted(by_lot, key=lambda l: (l.removal_date or '9999-12-31', l.id)):
            available = by_lot[lot]
            if available <= 0:
                continue
            lines.append((lot, available))
            covered += available
            if covered + 0.0001 >= need:
                break
        return lines

    def action_open_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Material Pickings'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('x_mes_order_id', '=', self.id)],
            'context': {'default_x_mes_order_id': self.id},
        }

    @api.depends('picking_ids')
    def _compute_picking_count(self):
        for order in self:
            order.picking_count = len(order.picking_ids)

    def _sn_sequence(self):
        """SN numbering sequence of this order's product: drawing-number
        prefix + serial. The prefix stays empty until drawing numbers are
        configured (test phase)."""
        self.ensure_one()
        production = self.production_id
        prefix = production.product_id.default_code or ''
        code = 'sn.wsd.serial.identity.product.%s' % production.product_id.id
        sequence = self.env['ir.sequence'].sudo().search([('code', '=', code)], limit=1)
        if not sequence:
            sequence = self.env['ir.sequence'].sudo().create({
                'name': 'SN %s' % production.display_name,
                'code': code,
                'prefix': prefix,
                'padding': 5,
                'company_id': production.company_id.id,
            })
        return sequence

    def generate_sn(self):
        """Reserve the next SN identity for this order (device calls the
        next-sn endpoint; the order form button generates in batch)."""
        self.ensure_one()
        serial_no = self._sn_sequence().sudo().next_by_code(
            self._sn_sequence().code)
        if not serial_no:
            raise ValidationError(_('No SN sequence is configured.'))
        return self.env['sn.wsd.serial.identity'].create({
            'name': serial_no,
            'company_id': self.company_id.id,
            'origin_type': 'manual',
            'origin_production_id': self.production_id.id,
        })

    def action_generate_sns(self, quantity=1):
        self.ensure_one()
        identities = self.env['sn.wsd.serial.identity']
        for _index in range(int(quantity)):
            identities |= self.generate_sn()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated SNs'),
            'res_model': 'sn.wsd.serial.identity',
            'view_mode': 'list',
            'domain': [('id', 'in', identities.ids)],
        }

class StockPickingMesOrder(models.Model):
    """Link a material picking back to its MES order (F5).

    ``x_mes_order_qty`` carries the finished-unit quantity this picking
    covers; validating a picking advances the linked MES order through the
    single transition point ``_update_pick_state`` (PRD I4).
    """
    _inherit = 'stock.picking'

    x_mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order',
        ondelete='set null', index=True, check_company=True, copy=False,
    )
    x_mes_order_qty = fields.Float(
        string='MES Order Units', copy=False,
        help='Finished-unit quantity this picking covers; used to '
             'accumulate the MES order picked quantity.',
    )
    x_is_over_pick = fields.Boolean(
        string='Over-pick', copy=False,
        help='This picking issues material beyond the planned quantity.',
    )
    x_over_reason = fields.Text(
        string='Over-pick Reason', copy=False,
    )

    def action_open_mes_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('MES Order'),
            'res_model': 'sn.wsd.mes.order',
            'view_mode': 'form',
            'res_id': self.x_mes_order_id.id,
        }

    def button_validate(self):
        res = super().button_validate()
        # single-point released -> picked transition; _update_pick_state
        # itself skips orders that are no longer released (cancelled etc.)
        self.mapped('x_mes_order_id')._update_pick_state()
        return res


class MrpBomLineMesAdvanceIssue(models.Model):
    """Pre-issue flag on BOM lines (架构设计 2.4).

    Materials flagged here (solder paste and the like) are issued to the
    line side ahead of time and are excluded from MES-order pickings (PRD
    F5 R1 / D8). Flagging is done on the BOM itself; no management view.
    """
    _inherit = 'mrp.bom.line'

    x_advance_issue = fields.Boolean(
        string='Advance Issue',
        help='Pre-issued to the line side; excluded from MES order pickings.',
    )


class StockWarehouseMesIssue(models.Model):
    """Dedicated per-warehouse "Material Issue" operation type for MES
    requisitions (领料单)."""
    _inherit = 'stock.warehouse'

    picking_type_issue_id = fields.Many2one(
        'stock.picking.type', string='Material Issue Operation',
        copy=False,
        help='Internal operation type used by MES-order material requisitions; '
             'created on first use.',
    )
    picking_type_return_id = fields.Many2one(
        'stock.picking.type', string='Material Return Operation',
        copy=False,
        help='Internal operation type used by MES-order material returns; '
             'created on first use.',
    )
    picking_type_over_pick_id = fields.Many2one(
        'stock.picking.type', string='Material Over-pick Operation',
        copy=False,
        help='Internal operation type used by MES-order over-picks (beyond '
             'the plan); created on first use.',
    )
    picking_type_receipt_id = fields.Many2one(
        'stock.picking.type', string='Finished Goods Receipt Operation',
        copy=False,
        help='Internal operation type used by MES-order completion receipts; '
             'created on first use.',
    )


class MesOrderOnlineLog(models.Model):
    """Who put a MES order online / offline, and when (上下线日志)."""

    _name = 'sn.wsd.mes.order.log'
    _description = 'MES Order Online Log'
    _order = 'date desc, id desc'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', required=True, ondelete='cascade', index=True,
        check_company=True,
    )
    action = fields.Selection(
        [('online', 'Go Online'), ('offline', 'Go Offline')],
        string='Action', required=True, index=True,
    )
    user_id = fields.Many2one(
        'res.users', string='User', default=lambda self: self.env.user,
        required=True, index=True,
    )
    date = fields.Datetime(string='Date', default=fields.Datetime.now,
                           required=True, index=True)
    company_id = fields.Many2one(
        'res.company', related='mes_order_id.company_id', store=True,
    )
