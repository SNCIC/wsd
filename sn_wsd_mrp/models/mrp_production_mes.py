from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .constants import SIDE_LABELS, board_side_required_sides


class MrpProductionMesSchedule(models.Model):
    """MES scheduling info on the mother MO (PRD F1).

    These are all computed fields -- nothing is entered by hand. They react to
    create/write/unlink/state-change of the MO's MES orders (制令单).
    """
    _inherit = 'mrp.production'

    # product-level gate: only flagged products use the MES scheduling flow
    x_use_daily_plan = fields.Boolean(
        string='Use MES Scheduling',
        related='product_id.x_use_daily_plan',
        store=True,
    )

    x_mes_order_ids = fields.One2many(
        'sn.wsd.mes.order', 'production_id', string='MES Orders',
    )
    x_mes_picking_count = fields.Integer(
        string='MES Transfers Count', compute='_compute_x_mes_picking_count',
        help='Number of stock documents (issues, returns, completion '
             'receipts) carried by this MO\'s MES orders.',
    )
    x_mes_order_count = fields.Integer(
        compute='_compute_x_mes_schedule', store=True,
    )
    x_mes_scheduled_qty = fields.Float(
        string='Scheduled Quantity', compute='_compute_x_mes_schedule', store=True,
    )
    x_mes_unscheduled_qty = fields.Float(
        string='Unscheduled Quantity', compute='_compute_x_mes_schedule', store=True,
    )
    x_mes_produced_qty = fields.Float(
        string='Produced Quantity', compute='_compute_x_mes_schedule', store=True,
    )
    x_mes_schedule_state = fields.Selection(
        [('unplanned', 'Unplanned'),
         ('partial', 'Partial'),
         ('planned', 'Planned')],
        string='Schedule State', compute='_compute_x_mes_schedule', store=True,
    )
    x_last_replenishment_date = fields.Datetime(
        string='Last Replenishment Date', copy=False, readonly=True,
    )
    x_replenishment_move_ids = fields.Many2many(
        'stock.move', string='Replenishment Moves',
        compute='_compute_x_replenishment',
    )
    x_replenishment_po_ids = fields.Many2many(
        'purchase.order', string='Replenishment Purchase Orders',
        compute='_compute_x_replenishment',
    )
    # ------------------------------------------------------------------
    # Process route check (工艺路线检查视图) -- per-MO answer to "does the
    # product's board side + workshop + drawing match a live route?". The
    # sides required come from the product's board side type; the workshop
    # from the MO. MOs whose product has no 图号 (default_code) are out of
    # scope and never flagged.
    # ------------------------------------------------------------------
    x_drawing_no = fields.Char(
        related='product_id.default_code', string='Drawing No.',
    )
    x_board_side = fields.Selection(
        related='product_id.x_board_side', string='Board Side Type',
    )
    x_mes_route_single_ok = fields.Boolean(
        string='Single Side Route', compute='_compute_x_mes_route_check',
        help='True when a live (confirmed + active) process route matches '
             'this MO for the single side (车间 + 图号; side-less routes '
             'count as single).',
    )
    x_mes_route_top_ok = fields.Boolean(
        string='Top (T) Side Route', compute='_compute_x_mes_route_check',
        help='True when a live process route matches this MO for the Top (T) '
             'side (车间 + 图号 + 面别).',
    )
    x_mes_route_bottom_ok = fields.Boolean(
        string='Bottom (B) Side Route', compute='_compute_x_mes_route_check',
        help='True when a live process route matches this MO for the Bottom '
             '(B) side (车间 + 图号 + 面别).',
    )
    x_mes_route_missing_sides = fields.Char(
        string='Missing Route Sides', compute='_compute_x_mes_route_check',
        help='Sides required by the product board side type with no matching '
             'live route for this MO (车间 + 图号 + 面别).',
    )
    x_mes_route_missing = fields.Boolean(
        string='Route Not Matched', compute='_compute_x_mes_route_check',
        search='_search_x_mes_route_missing',
        help='True when at least one required side of this MO has no matching '
             'live process route.',
    )

    @api.depends('product_id.default_code', 'product_id.x_board_side', 'x_workshop_id')
    def _compute_x_mes_route_check(self):
        Route = self.env['sn.wsd.process.route']
        # one side map per workshop (None = MO without a workshop: any
        # workshop's route matches -- the one kept degradation, for MOs
        # without a BOM workshop)
        by_workshop = {}
        for production in self:
            by_workshop.setdefault(production.x_workshop_id.id or None, []).append(
                production)
        maps = {}
        for workshop_id, prods in by_workshop.items():
            drawings = list({p.product_id.default_code for p in prods
                             if p.product_id.default_code})
            maps[workshop_id] = Route._mes_side_route_map(
                drawings, workshop_id=workshop_id)
        for production in self:
            routes = maps.get(
                production.x_workshop_id.id or None, {}
            ).get(production.product_id.default_code) or {}
            production.x_mes_route_single_ok = bool(routes.get('single'))
            production.x_mes_route_top_ok = bool(routes.get('top'))
            production.x_mes_route_bottom_ok = bool(routes.get('bottom'))
            required = board_side_required_sides(
                production.product_id.x_board_side)
            if not production.product_id.default_code:
                # no 图号: out of scope for route matching
                production.x_mes_route_missing_sides = False
                production.x_mes_route_missing = False
            elif required is None:
                # drawing product without a board side type: incomplete
                # master data -- flag it so the check view drives the fix
                production.x_mes_route_missing_sides = _('Board Side Type')
                production.x_mes_route_missing = True
            else:
                missing = {side for side in required if not routes.get(side)}
                production.x_mes_route_missing_sides = ', '.join(
                    _(SIDE_LABELS[side]) for side in sorted(missing)) or False
                production.x_mes_route_missing = bool(missing)

    def _search_x_mes_route_missing(self, operator, value):
        """Domain for the default filter of the process route check view:
        evaluate the compute on open MOs of drawing products (non-stored).

        Odoo 19 normalizes boolean ``=`` / ``!=`` into ``in`` / ``not in``
        before calling this, so all four operators must be handled.
        """
        productions = self.search([
            ('state', 'not in', ('done', 'cancel')),
            ('product_id.default_code', '!=', False),
        ])
        missing = productions.filtered(lambda p: p.x_mes_route_missing)
        if operator in ('=', '=='):
            values, op = [value], 'in'
        elif operator == '!=':
            values, op = [value], 'not in'
        elif operator in ('in', 'not in'):
            values, op = list(value), operator
        else:
            raise NotImplementedError(
                'unsupported operator %r on x_mes_route_missing' % (operator,))
        if op == 'in':
            include_missing, include_ok = True in values, False in values
        else:
            include_missing, include_ok = True not in values, False not in values
        if include_missing and include_ok:
            selected = productions
        elif include_missing:
            selected = missing
        elif include_ok:
            selected = productions - missing
        else:
            selected = self.browse()
        return [('id', 'in', selected.ids)]

    # ------------------------------------------------------------------
    # per-side [Add Route] buttons of the check view: open a new route form
    # prefilled with the MO's workshop + drawing + the missing side
    # ------------------------------------------------------------------
    def _mes_open_route_create(self, side):
        self.ensure_one()
        return self.env['sn.wsd.process.route']._mes_open_route_create_action(
            self.product_id.default_code, side,
            workshop_id=self.x_workshop_id.id)

    def action_open_mes_pickings(self):
        """Smart button on the MO: every stock document carried by its MES
        orders (material issues, returns, completion receipts) -- they all
        hang off ``x_mes_order_id``."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('MES Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('x_mes_order_id', 'in', self.x_mes_order_ids.ids)],
        }

    def action_mes_add_single_route(self):
        return self._mes_open_route_create('single')

    def action_mes_add_top_route(self):
        return self._mes_open_route_create('top')

    def action_mes_add_bottom_route(self):
        return self._mes_open_route_create('bottom')

    @api.depends('x_mes_order_ids.picking_ids')
    def _compute_x_mes_picking_count(self):
        for production in self:
            production.x_mes_picking_count = len(
                production.x_mes_order_ids.picking_ids)

    @api.depends(
        'product_qty',
        'x_mes_order_ids',
        'x_mes_order_ids.planned_qty',
        'x_mes_order_ids.produced_qty',
        'x_mes_order_ids.state',
    )
    def _compute_x_mes_schedule(self):
        for production in self:
            orders = production.x_mes_order_ids.filtered(lambda o: o.state != 'cancelled')
            scheduled = sum(orders.mapped('planned_qty'))
            produced = sum(orders.mapped('produced_qty'))
            production.x_mes_order_count = len(orders)
            production.x_mes_scheduled_qty = scheduled
            production.x_mes_unscheduled_qty = production.product_qty - scheduled
            production.x_mes_produced_qty = produced
            if scheduled <= 0:
                production.x_mes_schedule_state = 'unplanned'
            elif scheduled >= production.product_qty - 0.0001:
                production.x_mes_schedule_state = 'planned'
            else:
                production.x_mes_schedule_state = 'partial'

    def _compute_x_replenishment(self):
        """Unfinished replenishment documents of this MO (F4 R3 traceability).

        Odoo 19 removed procurement groups; native replenishment propagates
        the procurement ``origin`` to both the created moves and the purchase
        orders, so the MO name is the traceability anchor. The MO's own raw
        moves are excluded (they carry the same origin but belong to the
        manufacturing demand, not to replenishment suggestions).
        """
        Move = self.env['stock.move']
        PurchaseOrder = self.env['purchase.order']
        for production in self:
            moves = Move.search([
                ('origin', '=', production.name),
                ('raw_material_production_id', '=', False),
                ('production_id', '=', False),
                ('state', 'not in', ('done', 'cancel')),
            ])
            orders = PurchaseOrder.search([
                ('origin', '=', production.name),
                ('state', 'not in', ('done', 'cancel')),
            ])
            production.x_replenishment_move_ids = moves
            production.x_replenishment_po_ids = orders

    # ------------------------------------------------------------------
    # online state: carried by the MES orders (制令单), not by the MO
    # ------------------------------------------------------------------
    def _has_online_mes_order(self):
        """Filter self down to the MOs carrying at least one online MES order.

        Online (上线) is a MES-order-level concept: an MO counts as online
        while any of its non-finished orders has ``x_online_date`` set.
        """
        online_orders = self.env['sn.wsd.mes.order'].search([
            ('production_id', 'in', self.ids),
            ('x_online_date', '!=', False),
            ('state', 'not in', ('done', 'cancelled')),
        ])
        return self.browse(online_orders.mapped('production_id').ids)

    def _action_online_mes_orders(self):
        """Put this MO's released MES orders online (制令单上线).

        Replaces the legacy MO-level auto-online: same trigger points, but
        the online flag now lands on the MES orders (state released ->
        in_progress, SN feeding gate opens there).
        """
        orders = self.x_mes_order_ids.filtered(
            lambda order: order.state == 'released' and not order.x_online_date)
        orders.action_online()
        return orders

    # ------------------------------------------------------------------
    # F4: replenishment suggestions -- native procurement, no custom
    # shortage algorithm (架构设计 3.4, adapted to Odoo 19 which dropped
    # procurement groups: traceability goes through the MO name in
    # ``origin``). Full-BOM scope (pre-issue materials included): the
    # MES-order picking is the issue action, this is only the warehouse
    # preparation trigger, the two never generate each other.
    # ------------------------------------------------------------------
    def action_generate_replenishment(self):
        Rule = self.env['stock.rule']
        for production in self:
            bom = production.bom_id
            if not bom:
                raise UserError(_(
                    'Manufacturing order %(mo)s has no BOM; cannot generate '
                    'replenishment suggestions.', mo=production.display_name))
            warehouse = production.picking_type_id.warehouse_id
            if not warehouse:
                raise UserError(_(
                    'The operation type of %(mo)s has no warehouse; cannot '
                    'generate replenishment suggestions.', mo=production.display_name))
            ratio = (production.product_qty / bom.product_qty) if bom.product_qty else 0.0
            # outstanding raw demand of this MO, per product, in the product's
            # own UoM -- the forecast below already counts it as outgoing, so
            # it must be added back or the MO would double-subtract itself.
            # Only the states the forecast actually counts (draft raw moves
            # are NOT in virtual_available's outgoing).
            own_demand = {}
            for move in production.move_raw_ids.filtered(
                    lambda m: m.state in ('waiting', 'confirmed', 'assigned', 'partially_available')):
                product = move.product_id
                own_demand[product] = own_demand.get(product, 0.0) + \
                    move.product_uom._compute_quantity(move.product_uom_qty, product.uom_id)
            procurements = []
            for line in bom.bom_line_ids:
                demand = line.product_qty * ratio  # in BOM-line UoM
                demand_product_uom = line.product_uom_id._compute_quantity(
                    demand, line.product_id.uom_id)
                # forecast availability = on hand + incoming (confirmed
                # purchases/transfers in transit) - outgoing (other orders'
                # demand); this MO's own demand is added back on top
                forecast = line.product_id.with_context(
                    warehouse=warehouse.id).virtual_available
                available = forecast + own_demand.get(line.product_id, 0.0)
                shortfall = demand_product_uom - available
                if shortfall <= 0.0001:
                    continue  # on hand or in transit covers it -> no suggestion
                procurements.append(Rule.Procurement(
                    line.product_id,
                    line.product_id.uom_id._compute_quantity(shortfall, line.product_uom_id),
                    line.product_uom_id,
                    warehouse.lot_stock_id,
                    production.display_name,
                    production.name,
                    production.company_id,
                    {
                        'warehouse_id': warehouse,
                        'date_planned': production.date_start or fields.Datetime.now(),
                    },
                ))
            if procurements:
                Rule.run(procurements)
            production.x_last_replenishment_date = fields.Datetime.now()
        return True
