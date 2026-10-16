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

    _check_approved_qty = models.Constraint(
        'CHECK(approved_qty >= 0 AND approved_qty <= product_qty)',
        'The approved quantity must be between zero and the requested quantity.',
    )

    @api.depends('approved_qty', 'qty_done')
    def _compute_approved_pending_qty(self):
        for line in self:
            line.approved_pending_qty = max(line.approved_qty - line.purchased_qty, 0.0)

    @api.depends(
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
        for line in self:
            tax_included_amount = 0.0
            purchased_qty = 0.0
            for purchase_line in line.purchase_lines.filtered(
                lambda purchase_line: purchase_line.state != 'cancel'
            ):
                order = purchase_line.order_id
                amount = purchase_line.price_total
                if order.currency_id != line.currency_id:
                    amount = order.currency_id._convert(
                        amount,
                        line.currency_id,
                        line.company_id,
                        (order.date_order or fields.Datetime.now()).date(),
                        round=False,
                    )
                tax_included_amount += amount
                if line.product_uom_id:
                    purchased_qty += purchase_line.product_uom_id._compute_quantity(
                        purchase_line.product_qty,
                        line.product_uom_id,
                    )
                else:
                    purchased_qty += purchase_line.product_qty
            line.tax_included_amount = tax_included_amount
            line.tax_included_unit_price = (
                tax_included_amount / purchased_qty if purchased_qty else 0.0
            )

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
        'purchase_lines',
        'purchase_lines.product_qty',
        'purchase_lines.product_uom_id',
        'purchase_lines.state',
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
