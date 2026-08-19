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
    internal_serial_count = fields.Integer(
        string='Internal Serials', compute='_compute_internal_serial_count',
        help='Boards tracked under the parent manufacturing order. Becomes '
             'order-scoped once serials carry their MES order link.',
    )
    internal_serial_ids = fields.One2many(
        'sn.wsd.internal.serial', 'mes_order_id', string='Internal Serial Records',
    )
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
                    return len(op.serial_history_ids) + len(op.serial_wip_ids) if op else 0
                out_op = route.x_daily_output_operation_id
                order.x_input_qty = _entered(route.x_daily_input_operation_id)
                order.x_output_qty = len(
                    out_op.serial_history_ids.filtered(lambda h: h.result == 'ok')
                ) if out_op else 0.0
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
    @api.depends('picking_ids.x_mes_order_qty', 'picking_ids.state')
    def _compute_picked_qty(self):
        for order in self:
            done = order.picking_ids.filtered(lambda p: p.state == 'done')
            order.picked_qty = sum(done.mapped('x_mes_order_qty'))

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

    def action_online(self):
        """Put the order online: SN feeding is allowed from this moment on,
        the mode is locked and the common route stops auto-syncing in."""
        for order in self:
            if order.x_online_date:
                raise ValidationError(_(
                    'MES order %(name)s is already online.', name=order.name))
            if order.state == 'cancelled':
                raise ValidationError(_(
                    'MES order %(name)s is cancelled and cannot go online.',
                    name=order.name))
            order.x_online_date = fields.Datetime.now()
            if order.state == 'released':
                order.state = 'in_progress'
            self.env['sn.wsd.mes.order.log'].create(
                {'mes_order_id': order.id, 'action': 'online'})

    def action_offline(self):
        """Take the order offline: SN feeding stops from this moment on.

        Blocked while boards are still in progress on this order -- going
        offline hides the order from the stations, and in-progress boards
        would lose their exit station. A log line keeps who/when."""
        Wip = self.env['sn.wsd.serial.wip']
        for order in self:
            if not order.x_online_date:
                raise ValidationError(_(
                    'MES order %(name)s is not online.', name=order.name))
            wip_sn = Wip.search_count([('mes_order_id', '=', order.id)])
            if wip_sn:
                raise ValidationError(_(
                    'MES order %(name)s still has %(count)s board(s) in '
                    'progress; let them leave their stations before going '
                    'offline.', name=order.name, count=wip_sn))
            order.x_online_date = False
            self.env['sn.wsd.mes.order.log'].create(
                {'mes_order_id': order.id, 'action': 'offline'})

    @api.depends('x_online_date')
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
        if not self.x_online_date:
            raise ValidationError(_(
                'MES order %(name)s is not online yet.', name=self.name))
        ops = self.x_mes_route_id.operation_ids
        return ops._reachable_operations(self, serial_identity)

    # ------------------------------------------------------------------
    # station entry by work center (the field-facing interface)
    # ------------------------------------------------------------------
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
        if not self.x_online_date:
            raise ValidationError(_(
                'MES order %(name)s is not online yet.', name=self.name))
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
        if walked.filtered(lambda h: h.route_operation_id == route_operation):
            raise ValidationError(_(
                'SN %(sn)s already passed operation %(op)s.',
                sn=serial_identity.name, op=route_operation.display_label))
        if not walked and not route_operation.x_allow_entry:
            raise ValidationError(_(
                'SN %(sn)s has not entered MES order %(order)s yet; it must '
                'be fed in from a start operation (%(op)s is not one).',
                sn=serial_identity.name, order=self.name,
                op=route_operation.display_label))
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

    def leave_station(self, serial_identity, result, scrap_reason=False):
        """Station mode: an SN leaves its current station.

        result: 'ok' counts as completed and unlocks the successors; 'ng'
        does not (repair handling is a later flow); 'scrap' is terminal:
        the board is gone, its components are scrapped from the line side
        through a native scrap order and the SN is sealed for this order.
        Returns True when the SN left through an end operation with OK --
        its flow on this order is finished."""
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
        self.env['sn.wsd.serial.operation.history'].sudo().create({
            'serial_identity_id': serial_identity.id,
            'mes_order_id': self.id,
            'route_operation_id': route_operation.id,
            'workcenter_id': wip.workcenter_id.id,
            'result': result,
            'in_date': wip.in_date,
            'out_date': fields.Datetime.now(),
        })
        wip.sudo().unlink()
        return bool(result == 'ok' and route_operation.x_allow_exit)

    def report_operation_qty(self, route_operation, qty_ok, qty_ng=0.0,
                              qty_scrap=0.0, scrap_reason=False):
        """Report mode: report one batch of an operation.

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
        if not self.x_online_date:
            raise ValidationError(_(
                'MES order %(name)s is not online yet.', name=self.name))
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
        reachable = self.get_reachable_operations()
        if route_operation not in reachable:
            raise ValidationError(_(
                'Operation %(op)s cannot be reported yet: none of its '
                'predecessors is fully reported.',
                op=route_operation.display_label))
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
        through native scrap orders (stock.scrap), validated immediately."""
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
        ratio = qty_scrap / bom.product_qty
        for line in bom.bom_line_ids:
            scrap_qty = line.product_qty * ratio
            if scrap_qty <= 0.0001:
                continue
            Scrap.sudo().create({
                'product_id': line.product_id.id,
                'product_uom_id': line.product_uom_id.id,
                'scrap_qty': scrap_qty,
                'location_id': line_side.id,
                'origin': self.name,
                'name': _('Operation scrap: %(op)s (%(reason)s)',
                          op=route_operation.display_label,
                          reason=scrap_reason.display_name),
                'x_scrap_reason_id': scrap_reason.id if scrap_reason else False,
                'company_id': self.company_id.id,
            }).do_scrap()

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

    def _mes_backflush(self, qty):
        """Consume BOM materials x qty from the line side (no document,
        manufacturing-consumption style). Fails hard on line-side
        shortage -- the whole completion rolls back."""
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
        ratio = qty / bom.product_qty
        for line in bom.bom_line_ids:
            consume_qty = line.product_qty * ratio
            if consume_qty <= 0.0001:
                continue
            moves |= StockMove.create({
                'description_picking_manual': _('MES completion %(order)s', order=self.name),
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

    def _mes_create_receipt(self, qty, destination, workshop=False):
        """One completion receipt: production -> finished-goods stock
        (waiting for warehouse validation) or -> workshop line side
        (auto-validated)."""
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
        self.env['stock.move'].create({
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
        })
        picking.action_confirm()
        if destination == 'lineside':
            picking.button_validate()
        return picking

    def action_complete(self, qty, destination='stock', workshop=False):
        """Complete (完工入库) -- the single execution entry used by both
        the form wizard and the shop-floor terminal.

        1. backflush components from the line side (fails on shortage)
        2. create the completion receipt (auto-validated for line side)
        3. accumulate the done quantity; close the order and the MO when
           the output quantity is fully received"""
        self.ensure_one()
        if self.state != 'in_progress' or not self.x_online_date:
            raise ValidationError(_(
                'MES order %(name)s must be online and in progress to '
                'complete products.', name=self.name))
        if qty <= 0:
            raise ValidationError(_('The completion quantity must be positive.'))
        self._mes_backflush(qty)
        self._mes_create_receipt(qty, destination, workshop=workshop)
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

    def action_generate_picking(self, qty_this=None):
        """Generate one internal picking for ``qty_this`` finished units.

        ``qty_this`` is the batch quantity of this issue (架构设计 3.3); it
        defaults to whatever remains of the order quantity. The accumulated
        ``picked_qty`` may never exceed the order quantity.
        """
        StockMove = self.env['stock.move']
        StockPicking = self.env['stock.picking']
        PickingType = self.env['stock.picking.type']
        for order in self.filtered(lambda o: o.state == 'released'):
            if qty_this is None:
                qty_this = order.planned_qty - order.picked_qty
            if qty_this <= 0.0001:
                raise UserError(_(
                    'Nothing left to pick on MES order %(order)s.', order=order.name))
            if qty_this + order.picked_qty > order.planned_qty + 0.0001:
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
            # dedicated "Material Issue" operation type per warehouse: never
            # guess from code='internal' (Quality Control shares that code
            # and used to get picked by accident)
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
            picking = StockPicking.create({
                'picking_type_id': picking_type.id,
                'origin': order.name,
                'location_id': src.id,
                'location_dest_id': line_side.id,
                'company_id': order.company_id.id,
                'x_mes_order_id': order.id,
                'x_mes_order_qty': qty_this,
            })
            for line in bom.bom_line_ids:
                if line.x_advance_issue:
                    continue  # pre-issued to the line side, never on MES pickings
                batch_qty = line.product_qty * batch_ratio
                already = sum(
                    sum(p.move_ids.filtered(
                        lambda m: m.product_id == line.product_id
                    ).mapped('product_uom_qty'))
                    for p in open_pickings
                )
                remaining_total = line.product_qty * total_ratio - already
                qty = min(batch_qty, remaining_total)
                if qty <= 0.0001:
                    continue  # nothing left to issue for this component
                StockMove.create({
                    'product_id': line.product_id.id,
                    'product_uom': line.product_uom_id.id,
                    'product_uom_qty': qty,
                    'picking_id': picking.id,
                    'location_id': src.id,
                    'location_dest_id': line_side.id,
                    'company_id': order.company_id.id,
                })
            picking.action_confirm()
        return True

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

    def _compute_internal_serial_count(self):
        for order in self:
            order.internal_serial_count = len(order.internal_serial_ids)

    def action_open_internal_serials(self):
        self.ensure_one()
        production = self.production_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Internal Serials'),
            'res_model': 'sn.wsd.internal.serial',
            'view_mode': 'list,form',
            'domain': [('mes_order_id', '=', self.id)],
            'context': {
                'default_production_id': production.id,
                'default_product_id': production.product_id.id,
                'default_mes_order_id': self.id,
            },
        }

    def action_generate_missing_internal_serials(self, quantity=None):
        self.ensure_one()
        if self.state in ('cancelled', 'done'):
            raise ValidationError(_('Internal serials cannot be generated for a closed MES order.'))
        target_count = int(round(self.planned_qty))
        if target_count <= 0:
            raise ValidationError(_('The MES order planned quantity must be a positive whole number.'))
        active_serials = self.internal_serial_ids.filtered(
            lambda serial: serial.active and not serial.is_confirmed_scrapped()
        )
        missing_count = target_count - len(active_serials)
        if missing_count <= 0:
            return active_serials
        generate_count = min(int(quantity), missing_count) if quantity is not None else missing_count
        if generate_count <= 0:
            raise ValidationError(_('The internal serial generation quantity must be positive.'))
        self.production_id._lock_serial_capacity()
        values_list = []
        for _index in range(generate_count):
            serial_no = (
                self.env['ir.sequence'].next_by_code('sn.wsd.internal.serial.no')
                or self.env['ir.sequence'].next_by_code('sn.wsd.internal.serial')
            )
            if not serial_no:
                raise ValidationError(_('No internal serial number sequence is configured.'))
            values_list.append({
                'serial_no': serial_no,
                'barcode': serial_no,
                'product_id': self.product_id.id,
                'production_id': self.production_id.id,
                'current_production_id': self.production_id.id,
                'mes_order_id': self.id,
                'company_id': self.company_id.id,
                'serial_type': 'finished' if self.production_id.x_has_meter_operations else 'semifinished',
                'firmware_version': self.production_id.x_firmware_version,
                'customer_batch_no': self.production_id.x_delivery_batch_no,
            })
        return self.env['sn.wsd.internal.serial'].create(values_list)


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
