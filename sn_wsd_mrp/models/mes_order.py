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
        string='Reference', required=True, copy=False, readonly=True,
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
    produced_qty = fields.Float(string='Produced Quantity', default=0.0)
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
            if order.product_id.x_drawing_no and not board:
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

    def enter_station(self, serial_identity, route_operation):
        """Station mode: an SN enters an operation (its first station must be
        an input operation; later stations follow OR-reachability)."""
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
        if History.search_count([
            ('serial_identity_id', '=', serial_identity.id),
            ('route_operation_id', '=', route_operation.id),
        ]):
            raise ValidationError(_(
                'SN %(sn)s already passed operation %(op)s.',
                sn=serial_identity.name, op=route_operation.display_label))
        reachable = self.get_reachable_operations(serial_identity)
        if route_operation not in reachable:
            done = History.search([
                ('serial_identity_id', '=', serial_identity.id),
                ('mes_order_id', '=', self.id),
            ]).mapped('route_operation_id')
            raise ValidationError(_(
                'Operation %(op)s is not reachable for SN %(sn)s: none of its '
                'predecessors %(preds)s is completed yet.',
                op=route_operation.display_label, sn=serial_identity.name,
                preds=', '.join(route_operation.blocked_by_ids.mapped('display_label')) or '-'))
        Wip.create({
            'serial_identity_id': serial_identity.id,
            'mes_order_id': self.id,
            'route_operation_id': route_operation.id,
        })

    def leave_station(self, serial_identity, result):
        """Station mode: an SN leaves its current station.

        result: 'ok' counts as completed and unlocks the successors; 'ng'
        does not (repair/scrap handling is a separate, later flow)."""
        self.ensure_one()
        if result not in ('ok', 'ng'):
            raise ValidationError(_(
                "Leave result must be 'ok' or 'ng'."))
        Wip = self.env['sn.wsd.serial.wip']
        wip = Wip.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ], limit=1)
        if not wip:
            raise ValidationError(_(
                'SN %(sn)s is not in progress on MES order %(order)s.',
                sn=serial_identity.name, order=self.name))
        self.env['sn.wsd.serial.operation.history'].create({
            'serial_identity_id': serial_identity.id,
            'mes_order_id': self.id,
            'route_operation_id': wip.route_operation_id.id,
            'result': result,
            'in_date': wip.in_date,
            'out_date': fields.Datetime.now(),
        })
        wip.unlink()

    def report_operation_qty(self, route_operation, qty):
        """Report mode: add reported quantity to an operation.

        An operation is completed once the accumulated quantity reaches the
        order's planned quantity; predecessors must be completed first."""
        self.ensure_one()
        if self.x_manage_mode != 'report':
            raise ValidationError(_(
                'MES order %(name)s is managed by SN station tracking; '
                'operation reporting is not available.', name=self.name))
        if not self.x_online_date:
            raise ValidationError(_(
                'MES order %(name)s is not online yet.', name=self.name))
        if qty <= 0:
            raise ValidationError(_('The reported quantity must be positive.'))
        if route_operation.mes_route_id != self.x_mes_route_id:
            raise ValidationError(_(
                'Operation %(op)s does not belong to the route of MES order '
                '%(order)s.', op=route_operation.display_label, order=self.name))
        reachable = self.get_reachable_operations()
        if route_operation not in reachable:
            raise ValidationError(_(
                'Operation %(op)s cannot be reported yet: none of its '
                'predecessors is fully reported.',
                op=route_operation.display_label))
        self.env['sn.wsd.mes.operation.report'].create({
            'mes_order_id': self.id,
            'route_operation_id': route_operation.id,
            'qty': qty,
        })

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
        """Reserved hook for the execution layer (架构设计 3.5).

        Called when a MES order is completed and stored (完工入库): once every
        MES order of the MO is ``done``, the MO itself is closed. Not wired to
        anything in this scope -- the execution-layer PRD calls it.
        """
        for order in self:
            mo = order.production_id
            if mo.x_mes_order_ids and all(o.state == 'done' for o in mo.x_mes_order_ids):
                mo.button_mark_done()

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
        Serial = self.env['sn.wsd.internal.serial']
        for order in self:
            production = order.production_id
            if production.x_manufacturing_batch_id:
                domain = [('manufacturing_batch_id', '=', production.x_manufacturing_batch_id.id)]
            else:
                domain = [('production_id', '=', production.id)]
            order.internal_serial_count = Serial.search_count(domain)

    def action_open_internal_serials(self):
        self.ensure_one()
        production = self.production_id
        if production.x_manufacturing_batch_id:
            domain = [('manufacturing_batch_id', '=', production.x_manufacturing_batch_id.id)]
        else:
            domain = [('production_id', '=', production.id)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Internal Serials'),
            'res_model': 'sn.wsd.internal.serial',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {
                'default_production_id': production.id,
                'default_product_id': production.product_id.id,
            },
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
