from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PurchaseRequestLine(models.Model):
    _inherit = 'purchase.request.line'

    approved_qty = fields.Float(
        string='Approved Quantity',
        digits='Product Unit of Measure',
        copy=False,
        tracking=True,
        default=0.0,
        help='Quantity approved for purchasing. It defaults to the requested quantity when approval is requested.',
    )
    approved_pending_qty = fields.Float(
        string='Approved Quantity to Purchase',
        digits='Product Unit of Measure',
        compute='_compute_approved_pending_qty',
    )
    create_user_id = fields.Many2one(
        related='create_uid',
        string='Created By',
        readonly=True,
    )
    product_code = fields.Char(
        related='product_id.default_code',
        string='Material Code',
        readonly=True,
    )
    product_name = fields.Char(
        related='product_id.name',
        string='Material Name',
        readonly=True,
    )
    material_specification = fields.Char(
        related='product_id.material_specification',
        string='Material Specification',
        readonly=True,
    )
    requested_qty = fields.Float(
        related='product_qty',
        string='Requested Quantity',
        readonly=True,
    )
    received_qty = fields.Float(
        related='qty_done',
        string='Received Quantity',
        readonly=True,
    )
    tax_included_unit_price = fields.Monetary(
        string='Tax Included Unit Price',
        currency_field='currency_id',
        compute='_compute_tax_included_amounts',
    )
    tax_included_amount = fields.Monetary(
        string='Tax Included Amount',
        currency_field='currency_id',
        compute='_compute_tax_included_amounts',
    )
    purchase_order_ids = fields.Many2many(
        comodel_name='purchase.order',
        string='Purchase Orders',
        compute='_compute_purchase_order_ids',
        store=True,
        readonly=True,
    )
    expected_arrival_date = fields.Datetime(
        compute='_compute_expected_arrival_date',
        string='Expected Arrival',
        readonly=True,
    )
    receipt_status = fields.Selection(
        selection=[
            ('not_received', 'Not Received'),
            ('partially_received', 'Partially Received'),
            ('fully_received', 'Fully Received'),
        ],
        string='Receipt Status',
        compute='_compute_receipt_status',
        store=True,
        readonly=True,
    )
    po_supplier_id = fields.Many2one(
        comodel_name='res.partner',
        string='Supplier',
        compute='_compute_po_supplier_id',
        help='Supplier of the purchase order this request line was ordered on; '
             'empty until a purchase order is placed.',
    )
    qc_qty = fields.Float(
        string='Quality Control Quantity',
        digits='Product Unit of Measure',
        compute='_compute_reception_step_quantities',
        help='Quantity that has completed the quality control step of the reception.',
    )
    stocked_qty = fields.Float(
        string='Stocked Quantity',
        digits='Product Unit of Measure',
        compute='_compute_reception_step_quantities',
        help='Quantity that has completed the storage step of the reception.',
    )
    # The module reports a fully received line as 'done', a state the purchase
    # order no longer has in Odoo 19 (a completed order is a 'purchase' order
    # flagged as locked), so the selection is rebuilt with that value. A value
    # missing from the selection makes the web client fail to render the field.
    purchase_state = fields.Selection(selection='_selection_purchase_state')

    _check_approved_qty = models.Constraint(
        'CHECK(approved_qty >= 0 AND approved_qty <= product_qty)',
        'The approved quantity must be between zero and the requested quantity.',
    )

    @api.model
    def _selection_purchase_state(self):
        """Purchase status, including the receiving state of the line.

        The selection is the one of the purchase order, completed with the
        'done' state that the module still reports for a fully received line.
        That state is inserted before the cancelled one, so the choices read in
        the order the purchase goes through.
        """
        states = self.env['purchase.order']._fields['state']._description_selection(self.env)
        cancelled = [state for state in states if state[0] == 'cancel']
        options = [state for state in states if state[0] != 'cancel']
        options.append(('done', _('Fully Received')))
        options.extend(cancelled)
        return options

    @api.depends(
        'purchase_request_allocation_ids',
        'purchase_request_allocation_ids.requested_product_uom_qty',
        'purchase_request_allocation_ids.purchase_line_id',
        'purchase_request_allocation_ids.purchase_line_id.product_qty',
        'purchase_request_allocation_ids.purchase_line_id.product_uom_id',
        'purchase_request_allocation_ids.purchase_line_id.state',
        'purchase_lines',
        'purchase_lines.product_qty',
        'purchase_lines.product_uom_id',
        'purchase_lines.state',
        'product_uom_id',
    )
    def _compute_purchased_qty(self):
        """Ordered quantity, split between the lines sharing a purchase line.

        The module counts the whole quantity of a purchase order line on every
        request line linked to it, which counts the same goods once per line as
        soon as several request lines share an order line. The quantity is
        split between them here instead.
        """
        quantities = self._get_ordered_quantities()
        by_line = defaultdict(float)
        for (line_id, _purchase_line_id), quantity in quantities.items():
            by_line[line_id] += quantity
        for line in self:
            line.purchased_qty = by_line.get(line.id, 0.0)

    @api.depends(
        'purchase_lines',
        'purchase_lines.state',
        'purchase_lines.order_id.state',
        'purchase_lines.product_qty',
        'purchase_lines.qty_received',
        'purchase_request_allocation_ids',
        'purchase_request_allocation_ids.requested_product_uom_qty',
    )
    def _compute_purchase_state(self):
        """Follow the receipt as well as the state of the purchase order.

        The module only depends on the state of the purchase order, which does
        not change when the goods are received, so a fully received line kept
        the status of its order. The quantities the computation compares are
        added to its dependencies, and a line is only received in full when the
        order line it is split on is, and when a quantity is really ordered for
        it.
        """
        quantities = self._get_ordered_quantities()
        for line in self:
            line.purchase_state = line._get_purchase_state(quantities)

    def _get_purchase_state(self, quantities):
        """Purchase status of the line, given its split quantities.

        Same states as the module: the line follows the state of its orders,
        and 'done' is reported for a fully received order line. The quantities
        split on the line tell whether the line is really served by that order
        line.
        """
        self.ensure_one()
        purchase_lines = self.purchase_lines
        if not purchase_lines:
            return False
        if any(
            quantities.get((self.id, purchase_line.id))
            and purchase_line.qty_received >= purchase_line.product_qty
            and purchase_line.state == 'purchase'
            for purchase_line in purchase_lines
        ):
            return 'done'
        if all(purchase_line.state == 'cancel' for purchase_line in purchase_lines):
            return 'cancel'
        if any(purchase_line.state == 'purchase' for purchase_line in purchase_lines):
            return 'purchase'
        if any(purchase_line.state == 'to approve' for purchase_line in purchase_lines):
            return 'to approve'
        if any(purchase_line.state == 'sent' for purchase_line in purchase_lines):
            return 'sent'
        if all(purchase_line.state in ('draft', 'cancel') for purchase_line in purchase_lines):
            return 'draft'
        return False

    @api.depends('approved_qty', 'purchased_qty')
    def _compute_approved_pending_qty(self):
        for line in self:
            line.approved_pending_qty = max(line.approved_qty - line.purchased_qty, 0.0)

    @api.depends(
        'purchase_request_allocation_ids',
        'purchase_request_allocation_ids.requested_product_uom_qty',
        'purchase_request_allocation_ids.purchase_line_id',
        'purchase_lines',
        'purchase_lines.state',
        'purchase_lines.price_total',
        'purchase_lines.tax_ids',
        'purchase_lines.discount',
        'purchase_lines.product_qty',
        'purchase_lines.product_uom_id',
        'purchase_lines.order_id',
        'purchase_lines.order_id.currency_id',
        'purchase_lines.order_id.date_order',
        'currency_id',
        'product_uom_id',
    )
    def _compute_tax_included_amounts(self):
        """Tax included amounts of the quantities ordered for the line.

        The module keeps the whole amount of a purchase order line, which is
        counted once per request line when several request lines share the same
        order line. The amount follows the split quantities instead.
        """
        quantities = self._get_ordered_quantities()
        for line in self:
            tax_included_amount = 0.0
            ordered_qty = 0.0
            for purchase_line in line.purchase_lines.filtered(
                lambda purchase_line: purchase_line.state != 'cancel'
            ):
                quantity = quantities.get((line.id, purchase_line.id), 0.0)
                if not quantity or not purchase_line.product_qty:
                    continue
                ordered_qty += quantity
                order = purchase_line.order_id
                amount = self._quantity_in_uom(
                    quantity,
                    line.product_uom_id,
                    purchase_line.product_uom_id,
                ) * (purchase_line.price_total / purchase_line.product_qty)
                if order.currency_id != line.currency_id:
                    amount = order.currency_id._convert(
                        amount,
                        line.currency_id,
                        line.company_id,
                        (order.date_order or fields.Datetime.now()).date(),
                        round=False,
                    )
                tax_included_amount += amount
            line.tax_included_amount = tax_included_amount
            line.tax_included_unit_price = (
                tax_included_amount / ordered_qty if ordered_qty else 0.0
            )

    def _quantity_in_uom(self, quantity, from_uom, to_uom):
        """Quantity converted between two UoMs, kept as is when one is missing."""
        if not from_uom or not to_uom or from_uom == to_uom:
            return quantity
        return from_uom._compute_quantity(quantity, to_uom)

    def _get_ordered_quantities(self):
        """Quantity ordered for each request line, per purchase order line.

        A purchase order line is shared by every request line it was created
        for, so its quantity is split between them in the order the allocations
        were created, and capped by the quantity of the order line: the order
        may have been reduced after the request, in which case the quantities
        of the request lines no longer add up to the ordered one. The quantities
        are given in the UoM of the request line, keyed by request line and
        purchase order line.

        Request lines linked to the order line without an allocation take what
        is left, so the split still adds up to the ordered quantity.
        """
        quantities = defaultdict(float)
        purchase_lines = self.purchase_lines.filtered(lambda line: line.state != 'cancel')
        for purchase_line in purchase_lines:
            purchase_uom = purchase_line.product_uom_id
            remaining = purchase_line.product_qty
            covered = set()
            for allocation in purchase_line.purchase_request_allocation_ids.sorted('id'):
                request_line = allocation.purchase_request_line_id
                requested = self._quantity_in_uom(
                    allocation.requested_product_uom_qty,
                    allocation.product_uom_id,
                    purchase_uom,
                )
                quantity = min(requested, remaining)
                if quantity <= 0.0:
                    continue
                quantities[(request_line.id, purchase_line.id)] += self._quantity_in_uom(
                    quantity,
                    purchase_uom,
                    request_line.product_uom_id,
                )
                remaining -= quantity
                covered.add(request_line.id)
            if remaining <= 0.0:
                continue
            for request_line in purchase_line.purchase_request_lines.filtered(
                lambda line: line.id not in covered
            ).sorted('id'):
                requested = self._quantity_in_uom(
                    request_line.approved_qty or request_line.product_qty,
                    request_line.product_uom_id,
                    purchase_uom,
                )
                quantity = min(requested, remaining)
                if quantity <= 0.0:
                    continue
                quantities[(request_line.id, purchase_line.id)] += self._quantity_in_uom(
                    quantity,
                    purchase_uom,
                    request_line.product_uom_id,
                )
                remaining -= quantity
        return quantities

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'approved_qty' not in vals and 'product_qty' in vals:
                vals['approved_qty'] = vals['product_qty']
        return super().create(vals_list)

    @api.onchange('product_qty')
    def _onchange_product_qty_set_approved_qty(self):
        for line in self:
            if line.request_state in ('draft', 'to_approve'):
                line.approved_qty = line.product_qty

    @api.onchange('product_id')
    def onchange_product_id(self):
        result = super().onchange_product_id()
        for line in self:
            if line.request_state in ('draft', 'to_approve'):
                line.approved_qty = line.product_qty
        return result

    @api.depends('purchase_lines.order_id.partner_id')
    def _compute_po_supplier_id(self):
        # Supplier of the purchase order, not the product default vendor: a
        # request line shows a supplier only once it has been ordered.
        for line in self:
            line.po_supplier_id = line.purchase_lines.order_id.partner_id[:1]

    @api.depends('purchase_lines.order_id')
    def _compute_purchase_order_ids(self):
        for line in self:
            line.purchase_order_ids = line.purchase_lines.mapped('order_id')

    @api.depends('purchase_lines.date_planned')
    def _compute_expected_arrival_date(self):
        for line in self:
            dates = line.purchase_lines.mapped('date_planned')
            line.expected_arrival_date = min(dates) if dates else False

    @api.depends(
        'purchased_qty',
        'qty_done',
    )
    def _compute_receipt_status(self):
        """Receipt status follows the quantity received on the receipt.

        Odoo updates that quantity when the receipt operation is validated. On a
        three-step reception this means the goods have reached the input
        location; inspection and putaway are tracked by the quality-control and
        storage steps.
        """
        for line in self:
            if not line.purchased_qty or not line.qty_done:
                line.receipt_status = 'not_received'
            elif line.qty_done >= line.purchased_qty:
                line.receipt_status = 'fully_received'
            else:
                line.receipt_status = 'partially_received'

    @api.depends('purchase_lines', 'qty_done', 'product_uom_id')
    def _compute_reception_step_quantities(self):
        quantities = self._get_reception_step_quantities()
        for line in self:
            line_quantities = quantities.get(line.id, {})
            line.qc_qty = line_quantities.get('qc', 0.0)
            line.stocked_qty = line_quantities.get('storage', 0.0)

    def _get_reception_step(self, move):
        """Return the reception step a move of this line belongs to.

        ``'qc'`` and ``'storage'`` are the two steps that follow the receipt of
        a three steps reception; both are created by push rules, so the
        operation types tell them apart. Those operation types only exist once
        the warehouse reception is set to three steps, which is the same
        condition the other modules of this project use to decide whether the
        receipt already reaches the stock by itself.
        """
        self.ensure_one()
        picking_type = move.picking_type_id
        warehouse = picking_type.warehouse_id
        if not warehouse:
            return False
        qc_type = warehouse.qc_type_id
        if qc_type.active and picking_type == qc_type:
            return 'qc'
        store_type = warehouse.store_type_id
        if store_type.active:
            return 'storage' if picking_type == store_type else False
        return 'storage' if picking_type.code == 'incoming' else False

    def _get_reception_step_quantities(self):
        """Quantity of the quality control and the storage steps, per line.

        A three steps reception chains the moves with push rules
        (vendors -> input -> quality -> stock). Only the receipt move carries
        the purchase line, and the push rules clear it on the copies they
        create, so the downstream moves are walked down from the receipt move
        and attributed back to the request line through that origin move.

        Each quantity is capped by the quantity this line has allocated on the
        receipt move, so the three steps of the reception compare with each
        other (and with the received quantity) instead of reporting a
        downstream step higher than the receipt it comes from.

        Returns a dict of ``{line id: {'qc': quantity, 'storage': quantity}}``.
        """
        lines = self
        receipt_moves = self.env['stock.move'].search([
            ('purchase_line_id', 'in', lines.purchase_lines.ids),
        ])
        if not receipt_moves:
            return {}
        origin_moves = {move.id: move for move in receipt_moves}
        chain = receipt_moves
        frontier = receipt_moves
        while frontier:
            frontier = self.env['stock.move'].search([
                ('move_orig_ids', 'in', frontier.ids),
                ('id', 'not in', chain.ids),
            ])
            for move in frontier:
                parent = (move.move_orig_ids & chain)[:1]
                origin_moves[move.id] = origin_moves.get(parent.id, move)
            chain |= frontier
        allocations = defaultdict(float)
        for allocation in receipt_moves.purchase_request_allocation_ids:
            if allocation.purchase_request_line_id in lines:
                key = (allocation.stock_move_id.id,
                       allocation.purchase_request_line_id.id)
                allocations[key] += allocation.allocated_product_qty
        quantities = defaultdict(lambda: defaultdict(float))
        for move in chain:
            if move.state != 'done' or move.quantity <= 0.0:
                continue
            origin_move = origin_moves.get(move.id, move)
            for line in origin_move.purchase_line_id.purchase_request_lines & lines:
                step = line._get_reception_step(move)
                if not step:
                    continue
                uom = line.product_uom_id or move.product_uom
                quantity = move.product_uom._compute_quantity(
                    move.quantity, uom, rounding_method='HALF-UP')
                cap = allocations.get((origin_move.id, line.id))
                if cap is not None:
                    quantity = min(quantity, cap)
                quantities[line.id][step] += quantity
        return quantities

    def write(self, vals):
        if 'product_qty' in vals and 'approved_qty' not in vals:
            vals = dict(vals)
            vals['approved_qty'] = vals['product_qty']
        if 'approved_qty' in vals and not self.env.context.get('skip_approved_qty_lock'):
            for line in self:
                if line.request_state not in ('draft', 'to_approve'):
                    raise ValidationError(
                        _('Approved quantity can only be changed before the request is approved.')
                    )
        return super().write(vals)

    def _calc_new_qty(self, request_line, po_line=None, new_pr_line=False):
        quantity = super()._calc_new_qty(
            request_line,
            po_line=po_line,
            new_pr_line=new_pr_line,
        )
        if not po_line:
            return quantity
        purchase_uom = po_line.product_uom_id or request_line.product_id.uom_id
        approved_quantity = sum(
            line.product_uom_id._compute_quantity(line.approved_qty, purchase_uom)
            for line in po_line.purchase_request_lines.exists()
        )
        supplier_min_qty = self._get_supplier_min_qty(
            po_line.product_id,
            po_line.order_id.partner_id,
        ) if not po_line.order_id.dest_address_id else 0.0
        return max(approved_quantity, supplier_min_qty)


class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = 'purchase.request.line.make.purchase.order'

    @api.model
    def _prepare_item(self, line):
        item = super()._prepare_item(line)
        item['product_qty'] = line.approved_pending_qty
        return item

    @api.model
    def _prepare_purchase_order_line(self, po, item):
        vals = super()._prepare_purchase_order_line(po, item)
        product = item.product_id
        official_vals = self.env['purchase.order.line']._prepare_purchase_order_line(
            product,
            vals['product_qty'],
            product.uom_id,
            po.company_id,
            po.partner_id,
            po,
        )
        vals.update({
            'price_unit': official_vals['price_unit'],
            'tax_ids': official_vals['tax_ids'],
            'discount': official_vals['discount'],
        })
        return vals


class PurchaseRequest(models.Model):
    """Code a request the way the coding rules of the project do.

    The coding rule engine resets its counter on the period its sequence
    segment asks for, which the plain sequence of the module cannot do: the
    requests are numbered per month (PR-2026-10-0001). The sequence stays the
    fallback for a database where no rule is configured for the model.
    """

    _inherit = 'purchase.request'

    @api.model
    def _get_default_name(self):
        proxy = self.new({})
        rule = self.env['sn.code.rule']._find_rule(proxy)
        if rule:
            return rule.render(proxy)
        return self.env['ir.sequence'].next_by_code('purchase.request')
