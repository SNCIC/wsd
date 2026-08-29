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

    _check_approved_qty = models.Constraint(
        'CHECK(approved_qty >= 0 AND approved_qty <= product_qty)',
        'The approved quantity must be between zero and the requested quantity.',
    )

    @api.depends('approved_qty', 'qty_done')
    def _compute_approved_pending_qty(self):
        for line in self:
            line.approved_pending_qty = max(line.approved_qty - line.purchased_qty, 0.0)

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
        for line in self:
            if not line.purchased_qty or not line.qty_done:
                line.receipt_status = 'not_received'
            elif line.qty_done >= line.purchased_qty:
                line.receipt_status = 'fully_received'
            else:
                line.receipt_status = 'partially_received'

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
