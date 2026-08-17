from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..models.constants import SIDE_LABELS, SIDE_SELECTION


class MesScheduleWizard(models.TransientModel):
    """Scheduling dialog (排产弹窗) -- the single entry point that creates
    MES orders, opened from the [Schedule] button on the MO form (架构设计
    3.1). Manual creation in list views is turned off; correctness does not
    depend on that anyway, the same server-side rules (over-scheduling per
    side, active line, whole units, side/route match) run on create.

    Board sides are independent (面别各自独立): Top and Bottom each may cover
    the full MO quantity. The side dropdown is driven by the product's board
    side type -- single-sided products are fixed to Single, double-sided
    products choose Top/Bottom, legacy products (no board side type) keep a
    side-agnostic route lookup.
    """
    _name = 'sn.wsd.mes.schedule.wizard'
    _description = 'MES Scheduling Wizard'

    production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', required=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Product',
        related='production_id.product_id',
    )
    product_qty = fields.Float(
        string='MO Quantity', related='production_id.product_qty',
    )
    x_board_side = fields.Selection(
        related='product_id.x_board_side', string='Board Side Type',
    )
    x_side = fields.Selection(
        SIDE_SELECTION,
        string='Production Side', required=True, default='single',
        help='Side to schedule. Over-scheduling is checked per side: Top and '
             'Bottom may each cover the full MO quantity.',
    )
    x_side_route_id = fields.Many2one(
        'sn.wsd.process.route', string='Side Route',
        compute='_compute_route_status',
        help='Live (confirmed + active) process route that will be snapshotted '
             'into the MES order for the selected side.',
    )
    x_route_ok = fields.Boolean(
        string='Route Available', compute='_compute_route_status',
    )
    x_top_route_ok = fields.Boolean(
        string='Top (T) Route', compute='_compute_route_status',
    )
    x_bottom_route_ok = fields.Boolean(
        string='Bottom (B) Route', compute='_compute_route_status',
    )
    x_side_scheduled_qty = fields.Float(
        string='Side Scheduled Quantity', compute='_compute_side_qty',
        help='Quantity already scheduled on the selected side of this MO '
             '(non-cancelled MES orders only).',
    )
    x_side_remaining_qty = fields.Float(
        string='Side Remaining Quantity', compute='_compute_side_qty',
        help='Quantity still schedulable on the selected side.',
    )
    production_line_id = fields.Many2one(
        'sn.mrp.production.line', string='Production Line', required=True,
        domain=[('active', '=', True)],
    )
    date_plan = fields.Date(
        string='Plan Date', required=True, default=fields.Date.context_today,
    )
    qty = fields.Float(string='Quantity', required=True)

    # ------------------------------------------------------------------
    # side default follows the product's board side type
    # ------------------------------------------------------------------
    @api.onchange('production_id', 'product_id')
    def _onchange_production_id_side(self):
        for wizard in self:
            wizard.x_side = (
                'top' if wizard.product_id.x_board_side == 'double'
                else 'single')

    def _mes_resolver_side(self):
        """Side filter for the route lookup: None keeps the legacy
        side-agnostic behaviour for products without a board side type."""
        self.ensure_one()
        return self.x_side if self.product_id.x_board_side else None

    @api.depends('production_id', 'x_side', 'x_board_side', 'production_line_id')
    def _compute_route_status(self):
        Route = self.env['sn.wsd.process.route']
        for wizard in self:
            drawing = wizard.product_id.x_drawing_no
            company = wizard.production_id.company_id.id
            workshop = wizard.production_line_id.workshop_id.id
            wizard.x_top_route_ok = False
            wizard.x_bottom_route_ok = False
            wizard.x_side_route_id = False
            if drawing and not wizard.x_board_side:
                # 图号产品未声明板面类型：先补产品主数据，再排产
                wizard.x_route_ok = False
                continue
            routes = (
                Route._mes_side_route_map(
                    [drawing], company_id=company, workshop_id=workshop).get(drawing) or {}
                if drawing else {})
            if wizard.x_board_side:
                wizard.x_side_route_id = routes.get(wizard.x_side)
            else:
                # drawing-less products keep the side-agnostic lookup
                wizard.x_side_route_id = Route._find_current_route_by_drawing_no(
                    drawing, company, workshop_id=workshop)
            wizard.x_route_ok = bool(wizard.x_side_route_id)
            wizard.x_top_route_ok = bool(routes.get('top'))
            wizard.x_bottom_route_ok = bool(routes.get('bottom'))

    @api.depends('production_id', 'x_side')
    def _compute_side_qty(self):
        MesOrder = self.env['sn.wsd.mes.order']
        for wizard in self:
            scheduled = sum(MesOrder.search([
                ('production_id', '=', wizard.production_id.id),
                ('state', '!=', 'cancelled'),
                ('x_side', '=', wizard.x_side),
            ]).mapped('planned_qty'))
            wizard.x_side_scheduled_qty = scheduled
            wizard.x_side_remaining_qty = (
                wizard.production_id.product_qty - scheduled)

    def action_maintain_route(self):
        """[Maintain Route]: open a new route form prefilled with the line's
        workshop, the drawing number and the selected side; come back and
        schedule."""
        self.ensure_one()
        return self.env['sn.wsd.process.route']._mes_open_route_create_action(
            self.product_id.x_drawing_no, self.x_side,
            workshop_id=self.production_line_id.workshop_id.id)

    def action_schedule(self):
        self.ensure_one()
        production = self.production_id
        Route = self.env['sn.wsd.process.route']
        # -1) board side declaration gate: the board side type is the source
        #     of truth for side-based scheduling -- without it there is
        #     nothing to match against.
        if self.product_id.x_drawing_no and not self.product_id.x_board_side:
            raise ValidationError(_(
                'Product %(product)s has a drawing number but no board side '
                'type declared. Declare it on the product before scheduling.',
                product=self.product_id.display_name))
        side = self._mes_resolver_side()
        workshop = self.production_line_id.workshop_id
        # 0) route gate (架构设计 3.2): scheduling is blocked until the
        #    (workshop + drawing + side) route exists; the [Maintain Route]
        #    button fixes it.
        drawing = self.product_id.x_drawing_no
        route = Route._find_current_route_by_drawing_no(
            drawing, production.company_id.id, side=side,
            workshop_id=workshop.id)
        if not route:
            if side:
                raise ValidationError(_(
                    'The %(side)s-side process route of product %(drawing)s is '
                    'not maintained. Use the [Maintain Route] button to '
                    'complete it before scheduling.',
                    side=_(SIDE_LABELS[side]), drawing=drawing or _('(empty)'),
                ))
            raise ValidationError(_(
                'No released process route is bound to drawing number "%(drawing)s". '
                'Bind the route first.',
                drawing=drawing or _('(empty)'),
            ))
        # 1) regular gates: line workshop matches the MO workshop (the route
        #    check above and the process route check view both resolve by the
        #    MO's workshop -- a line from another workshop would silently
        #    diverge from them), active line, positive whole units
        if production.x_workshop_id and workshop != production.x_workshop_id:
            raise ValidationError(_(
                'Production line %(line)s belongs to workshop %(line_ws)s, '
                'but manufacturing order %(mo)s runs in workshop %(mo_ws)s. '
                'Pick a line of the MO workshop.',
                line=self.production_line_id.display_name,
                line_ws=workshop.display_name,
                mo=production.display_name,
                mo_ws=production.x_workshop_id.display_name))
        if not self.production_line_id.active:
            raise ValidationError(_(
                'Production line %(line)s is disabled and cannot be scheduled.',
                line=self.production_line_id.display_name))
        if self.qty <= 0 or self.qty != int(self.qty):
            raise ValidationError(
                _('The scheduled quantity must be a positive whole number of units.'))
        # 2) serialize concurrent scheduling on the same MO (架构设计 3.1): a
        #    second transaction waits on this lock, then re-reads the true
        #    per-side remaining quantity below.
        self.env.cr.execute(
            'SELECT id FROM mrp_production WHERE id = %s FOR UPDATE',
            [production.id])
        # fresh read after the lock -- the ORM cache may hold a stale total
        MesOrder = self.env['sn.wsd.mes.order']
        scheduled = sum(MesOrder.search([
            ('production_id', '=', production.id),
            ('state', '!=', 'cancelled'),
            ('x_side', '=', self.x_side),
        ]).mapped('planned_qty'))
        remaining = production.product_qty - scheduled
        if self.qty > remaining + 0.0001:
            raise ValidationError(_(
                'Over-scheduling: only %(remaining)s unit(s) remain for the '
                '%(side)s side of %(mo)s; %(qty)s was entered. Please adjust.',
                remaining=remaining, side=_(SIDE_LABELS[self.x_side]),
                mo=production.display_name, qty=self.qty))
        # 3) create: seq + name come from the per-MO counter, the route
        #    snapshot is resolved from (drawing, side) inside create()
        MesOrder.create({
            'production_id': production.id,
            'production_line_id': self.production_line_id.id,
            'date_plan': self.date_plan,
            'planned_qty': self.qty,
            'x_side': self.x_side,
        })
        return {'type': 'ir.actions.act_window_close'}
