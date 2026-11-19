from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tools import float_compare, float_is_zero


class SnTollOrder(models.Model):
    """Toll manufacturing order: the customer supplies the material, we
    process it and give the finished goods back.

    Neither the supplied material nor the finished goods belong to us. The
    ownership is carried by ``stock.move.line.owner_id`` (the standard
    consignment mechanism), which makes the stock valuation exclude those
    quants automatically. The order only recognises a processing fee.
    """

    _name = 'sn.toll.order'
    _description = 'Toll Manufacturing Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True
    _order = 'date_order desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Order Number', required=True, copy=False, readonly=True,
        default='/', index=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('in_progress', 'In Progress'),
            ('done', 'Done'),
            ('cancel', 'Cancelled'),
        ],
        string='Status', default='draft', required=True, copy=False,
        tracking=True, index=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, index=True,
        check_company=True, tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency', store=True,
        related='company_id.currency_id',
    )
    date_order = fields.Date(
        string='Order Date', required=True, tracking=True,
        default=fields.Date.context_today,
    )
    date_deadline = fields.Date(string='Delivery Deadline', tracking=True)
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order', copy=False, index=True,
        check_company=True, readonly=True,
        help='Sale order that launched the toll manufacturing: its lines '
             'carry the processing fee and the finished goods delivery.',
    )
    sale_line_id = fields.Many2one(
        'sale.order.line', string='Sale Order Line', copy=False, index=True,
        check_company=True, readonly=True,
    )
    is_linked_to_sale = fields.Boolean(
        string='Linked to a Sale Order', compute='_compute_is_linked_to_sale',
    )

    product_id = fields.Many2one(
        'product.product', string='Finished Product', required=True,
        check_company=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template', string='Product Template', store=True,
        related='product_id.product_tmpl_id', readonly=True,
    )
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit', store=True,
        related='product_id.uom_id', readonly=True,
    )
    product_qty = fields.Float(
        string='Quantity', required=True, default=1.0, digits='Product Unit',
    )
    bom_id = fields.Many2one(
        'mrp.bom', string='Bill of Materials', check_company=True,
        domain="[('type', '=', 'normal'), ('product_tmpl_id', '=', product_tmpl_id)]",
    )

    pricing_method = fields.Selection(
        selection=[
            ('piece_rate', 'Piece Rate'),
            ('fixed', 'Fixed Price'),
        ],
        string='Pricing Basis', default='fixed', required=True,
        help='Piece Rate reuses the processing price configured on a piece '
             'rate record; Fixed Price lets the processing fee be typed on '
             'the order.',
    )
    piece_rate_id = fields.Many2one(
        'sn.wsd.piece.rate', string='Piece Rate', check_company=True,
        domain="[('product_id', '=', product_id)]",
    )
    fee_unit = fields.Monetary(
        string='Processing Fee per Unit', currency_field='currency_id',
        help='Processing fee invoiced to the customer for one finished unit. '
             'Taken from the piece rate when the order is priced on a piece '
             'rate, and snapshotted so later rate changes do not rewrite the '
             'order.',
    )
    fee_product_id = fields.Many2one(
        'product.product', string='Processing Fee Product', check_company=True,
        domain="[('type', '=', 'service')]",
        help='Service product used on the processing fee invoice.',
    )
    fee_amount = fields.Monetary(
        string='Processing Fee', currency_field='currency_id',
        compute='_compute_fee_amounts', store=True, compute_sudo=True,
    )
    fee_deduction = fields.Monetary(
        string='Loss Deduction', currency_field='currency_id',
        compute='_compute_fee_amounts', store=True, compute_sudo=True,
        help='Amount deducted from the processing fee by the confirmed loss '
             'settlements that deduct from the fee.',
    )
    fee_net = fields.Monetary(
        string='Net Processing Fee', currency_field='currency_id',
        compute='_compute_fee_amounts', store=True, compute_sudo=True,
    )

    loss_policy = fields.Selection(
        selection=[
            ('deduct', 'Deduct from Processing Fee'),
            ('claim', 'Separate Claim Invoice'),
            ('resupply', 'Customer Resupply'),
        ],
        string='Default Loss Settlement', default='deduct', required=True,
        tracking=True,
        help='Settlement proposed when a loss settlement is created from this '
             'order. Any of the three settlements can still be chosen per '
             'document. The allowed loss percentage is tolerated: only the '
             'quantity above it is settled.',
    )
    loss_allowance = fields.Float(
        string='Allowed Loss (%)', default=0.0, digits=(5, 2),
        help='Percentage of the theoretical consumption tolerated before a '
             'loss is settled with the customer.',
    )

    material_line_ids = fields.One2many(
        'sn.toll.material.line', 'order_id', string='Supplied Material',
        copy=True,
    )
    production_ids = fields.One2many(
        'mrp.production', 'sn_toll_order_id', string='Manufacturing Orders',
        copy=False,
    )
    production_count = fields.Integer(
        string='MO Count', compute='_compute_production_count',
        compute_sudo=True,
    )
    material_picking_ids = fields.One2many(
        'stock.picking', 'sn_toll_order_id', string='Material Receipts',
        domain=[('sn_toll_receipt', '=', True)], copy=False,
    )
    delivery_picking_ids = fields.One2many(
        'stock.picking', 'sn_toll_order_id', string='Finished Goods Deliveries',
        domain=[('sn_toll_delivery', '=', True)], copy=False,
    )
    loss_ids = fields.One2many(
        'sn.toll.loss', 'order_id', string='Loss Settlements', copy=False,
    )
    account_move_ids = fields.One2many(
        'account.move', 'sn_toll_order_id', string='Invoices', copy=False,
    )
    invoice_count = fields.Integer(
        string='Invoice Count', compute='_compute_invoice_count',
        compute_sudo=True,
    )

    produced_qty = fields.Float(
        string='Produced Quantity', compute='_compute_progress', store=True,
        digits='Product Unit', compute_sudo=True,
    )
    delivered_qty = fields.Float(
        string='Delivered Quantity', compute='_compute_progress', store=True,
        digits='Product Unit', compute_sudo=True,
    )
    remaining_qty = fields.Float(
        string='Remaining to Deliver', compute='_compute_progress', store=True,
        digits='Product Unit', compute_sudo=True,
    )
    progress = fields.Float(
        string='Progress (%)', compute='_compute_progress', store=True,
        compute_sudo=True,
    )
    material_received_qty = fields.Float(
        string='Material Received', compute='_compute_material_totals',
        digits='Product Unit', compute_sudo=True,
    )
    material_consumed_qty = fields.Float(
        string='Material Consumed', compute='_compute_material_totals',
        digits='Product Unit', compute_sudo=True,
    )
    material_loss_qty = fields.Float(
        string='Material Loss', compute='_compute_material_totals',
        digits='Product Unit', compute_sudo=True,
    )
    material_stock_qty = fields.Float(
        string='Supplied Material in Stock', digits='Product Unit',
        compute='_compute_material_stock', compute_sudo=True,
        help='Quantity of supplied material currently stored for the '
             'customer. Computed as superuser so the customer portal can show '
             'it without granting access to the stock quants.',
    )
    note = fields.Html(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('sn.toll.order')
                    or '/')
        return super().create(vals_list)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and not self.product_uom_id:
            self.product_uom_id = self.product_id.uom_id
        if self.product_id:
            bom = self.env['mrp.bom']._bom_find(
                self.product_id, company_id=self.company_id.id,
                bom_type='normal').get(self.product_id)
            if bom:
                self.bom_id = bom

    @api.onchange('pricing_method', 'piece_rate_id')
    def _onchange_pricing(self):
        if self.pricing_method == 'piece_rate' and self.piece_rate_id:
            self.fee_unit = self.piece_rate_id.price

    @api.depends('fee_unit', 'product_qty', 'loss_ids.state', 'loss_ids.amount')
    def _compute_fee_amounts(self):
        for order in self:
            order.fee_amount = order.fee_unit * order.product_qty
            order.fee_deduction = sum(order.loss_ids.filtered(
                lambda loss: loss.state == 'done'
                and loss.settlement_type == 'deduct').mapped('amount'))
            order.fee_net = order.fee_amount - order.fee_deduction

    @api.depends('sale_order_id')
    def _compute_is_linked_to_sale(self):
        for order in self:
            order.is_linked_to_sale = bool(order.sale_order_id)

    @api.depends('production_ids')
    def _compute_production_count(self):
        for order in self:
            order.production_count = len(order.production_ids)

    @api.depends('account_move_ids')
    def _compute_invoice_count(self):
        for order in self:
            order.invoice_count = len(order.account_move_ids)

    @api.depends(
        'production_ids.qty_produced',
        'product_qty',
        'delivery_picking_ids.state',
        'delivery_picking_ids.move_line_ids.quantity',
    )
    def _compute_progress(self):
        for order in self:
            produced = sum(order.production_ids.mapped('qty_produced'))
            delivered = sum(
                order.delivery_picking_ids.filtered(
                    lambda picking: picking.state == 'done'
                ).move_line_ids.mapped('quantity'))
            order.produced_qty = produced
            order.delivered_qty = delivered
            order.remaining_qty = max(produced - delivered, 0.0)
            order.progress = (
                min(produced / order.product_qty * 100.0, 100.0)
                if order.product_qty else 0.0)

    @api.depends(
        'material_line_ids.qty_received',
        'material_line_ids.qty_consumed',
        'material_line_ids.qty_loss',
    )
    def _compute_material_totals(self):
        for order in self:
            order.material_received_qty = sum(
                order.material_line_ids.mapped('qty_received'))
            order.material_consumed_qty = sum(
                order.material_line_ids.mapped('qty_consumed'))
            order.material_loss_qty = sum(
                order.material_line_ids.mapped('qty_loss'))

    @api.depends('partner_id', 'company_id', 'material_line_ids.product_id')
    def _compute_material_stock(self):
        Quant = self.env['stock.quant'].sudo()
        for order in self:
            products = order.material_line_ids.product_id
            if not products or not order.partner_id:
                order.material_stock_qty = 0.0
                continue
            quants = Quant.search([
                ('product_id', 'in', products.ids),
                ('owner_id', '=', order.partner_id.id),
                ('location_id.usage', 'in', ('internal', 'transit')),
                ('company_id', '=', order.company_id.id),
            ])
            order.material_stock_qty = sum(quants.mapped('quantity'))

    @api.constrains('product_qty')
    def _check_product_qty(self):
        for order in self:
            if order.product_qty <= 0.0:
                raise ValidationError(_(
                    "The quantity of toll manufacturing order '%s' must be "
                    "greater than zero.", order.display_name))

    @api.constrains('loss_allowance')
    def _check_loss_allowance(self):
        for order in self:
            if not 0.0 <= order.loss_allowance <= 100.0:
                raise ValidationError(_(
                    'The allowed loss percentage must be between 0 and 100.'))

    def _get_warehouse(self):
        self.ensure_one()
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.company_id.id)], limit=1)
        if not warehouse:
            raise UserError(_(
                "No warehouse is configured for the company of toll "
                "manufacturing order '%s'.", self.display_name))
        return warehouse

    def _get_customer_location(self):
        self.ensure_one()
        location = self.partner_id.with_company(
            self.company_id).property_stock_customer
        if location and location.usage == 'customer':
            return location
        return self.env.ref('stock.stock_location_customers')

    def _get_supplier_location(self):
        self.ensure_one()
        location = self.partner_id.with_company(
            self.company_id).property_stock_supplier
        if location and location.usage == 'supplier':
            return location
        return self.env.ref('stock.stock_location_suppliers')

    def _get_consignment_picking_type(self, warehouse):
        self.ensure_one()
        return warehouse._ensure_consignment_in_type()

    def action_confirm(self):
        for order in self.filtered(lambda order: order.state == 'draft'):
            if not order.material_line_ids:
                raise UserError(_(
                    "Toll manufacturing order '%s' must list the material "
                    "supplied by the customer.", order.display_name))
            if not order.bom_id:
                raise UserError(_(
                    "Toll manufacturing order '%s' has no bill of materials: "
                    "the material consumption cannot be computed.",
                    order.display_name))
        self.write({'state': 'confirmed'})
        return True

    def action_create_material_receipt(self):
        """Create the consignment receipt of the material supplied by the
        customer. The customer is set as owner of the transfer, so the
        received quants stay out of our valuation."""
        self.ensure_one()
        if self.state == 'cancel':
            raise UserError(_(
                "Toll manufacturing order '%s' is cancelled.",
                self.display_name))
        if not self.material_line_ids:
            raise UserError(_(
                "Add the material supplied by the customer on toll "
                "manufacturing order '%s' before receiving it.",
                self.display_name))
        warehouse = self._get_warehouse()
        picking_type = self._get_consignment_picking_type(warehouse)
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'partner_id': self.partner_id.id,
            'owner_id': self.partner_id.id,
            'location_id': self._get_supplier_location().id,
            'location_dest_id': warehouse.lot_stock_id.id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'sn_toll_order_id': self.id,
            'sn_toll_receipt': True,
        })
        moves = self.env['stock.move']
        for line in self.material_line_ids:
            quantity = line.qty_to_receive
            if float_compare(
                    quantity, 0.0,
                    precision_rounding=line.product_id.uom_id.rounding) <= 0:
                continue
            moves |= self.env['stock.move'].create({
                'product_id': line.product_id.id,
                'product_uom': line.product_id.uom_id.id,
                'product_uom_qty': quantity,
                'picking_id': picking.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'company_id': self.company_id.id,
                'restrict_partner_id': self.partner_id.id,
            })
        if not moves:
            picking.unlink()
            raise UserError(_(
                "Every supplied material line of toll manufacturing order "
                "'%s' is already received.", self.display_name))
        picking.action_confirm()
        return self.action_view_picking(picking)

    def action_create_production(self):
        """Create the manufacturing order processing the supplied material."""
        self.ensure_one()
        if self.state not in ('confirmed', 'in_progress'):
            raise UserError(_(
                "Confirm toll manufacturing order '%s' before creating its "
                "manufacturing order.", self.display_name))
        existing = self.production_ids.filtered(
            lambda production: production.state != 'cancel')[:1]
        if existing:
            return self.action_view_production(existing)
        if not self.bom_id:
            raise UserError(_(
                "Toll manufacturing order '%s' has no bill of materials.",
                self.display_name))
        warehouse = self._get_warehouse()
        production = self.env['mrp.production'].create({
            'product_id': self.product_id.id,
            'product_qty': self.product_qty,
            'bom_id': self.bom_id.id,
            'picking_type_id': warehouse.manu_type_id.id,
            'company_id': self.company_id.id,
            'sn_toll_order_id': self.id,
            'sn_toll_partner_id': self.partner_id.id,
        })
        self.write({'state': 'in_progress'})
        return self.action_view_production(production)

    def action_create_delivery(self):
        """Deliver the finished goods back to the customer. The customer owns
        them: the transfer carries the customer as owner, so the delivery
        does not consume our valuation."""
        self.ensure_one()
        quantity = self.remaining_qty
        if float_compare(
                quantity, 0.0,
                precision_rounding=self.product_id.uom_id.rounding) <= 0:
            raise UserError(_(
                "Toll manufacturing order '%s' has no finished goods left to "
                "deliver.", self.display_name))
        warehouse = self._get_warehouse()
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.out_type_id.id,
            'partner_id': self.partner_id.id,
            'owner_id': self.partner_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self._get_customer_location().id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'sn_toll_order_id': self.id,
            'sn_toll_delivery': True,
        })
        self.env['stock.move'].create({
            'product_id': self.product_id.id,
            'product_uom': self.product_id.uom_id.id,
            'product_uom_qty': quantity,
            'picking_id': picking.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.company_id.id,
            'restrict_partner_id': self.partner_id.id,
        })
        picking.action_confirm()
        return self.action_view_picking(picking)

    def action_create_loss(self):
        self.ensure_one()
        loss = self.env['sn.toll.loss'].create({
            'order_id': self.id,
            'settlement_type': self.loss_policy,
        })
        loss.action_generate_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Loss Settlement'),
            'res_model': 'sn.toll.loss',
            'res_id': loss.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_invoice(self):
        """Invoice the processing fee, net of the deductions confirmed by the
        loss settlements."""
        self.ensure_one()
        if self.sale_order_id:
            # The sale order carries the processing fee lines, including the
            # deduction lines added by the loss settlements: invoice from it
            # so a single document bills the customer.
            invoice = self.sale_order_id._create_invoices()
            if not invoice:
                raise UserError(_(
                    "Nothing is left to invoice on sale order '%s'.",
                    self.sale_order_id.display_name))
            return {
                'type': 'ir.actions.act_window',
                'name': _('Invoice'),
                'res_model': 'account.move',
                'res_id': invoice[:1].id,
                'view_mode': 'form',
                'target': 'current',
            }
        if not self.fee_product_id:
            raise UserError(_(
                "Select the processing fee product on toll manufacturing "
                "order '%s' before invoicing.", self.display_name))
        lines = [Command.create({
            'product_id': self.fee_product_id.id,
            'name': _(
                'Processing fee - %(order)s - %(product)s',
                order=self.name, product=self.product_id.display_name),
            'quantity': self.product_qty,
            'price_unit': self.fee_unit,
        })]
        if self.fee_deduction > 0.0:
            lines.append(Command.create({
                'product_id': self.fee_product_id.id,
                'name': _('Loss deduction - %s', self.name),
                'quantity': 1.0,
                'price_unit': -self.fee_deduction,
            }))
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_origin': self.name,
            'sn_toll_order_id': self.id,
            'invoice_line_ids': lines,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_view_picking(self, picking):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer'),
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_production(self, production):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Manufacturing Order'),
            'res_model': 'mrp.production',
            'res_id': production.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_productions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'mrp.mrp_production_action')
        action['domain'] = [('sn_toll_order_id', '=', self.id)]
        action['context'] = {'default_sn_toll_order_id': self.id}
        return action

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'account.action_move_out_invoice_type')
        action['domain'] = [('sn_toll_order_id', '=', self.id)]
        action['context'] = {'default_move_type': 'out_invoice'}
        return action

    def action_view_material_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Material Receipts'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('sn_toll_order_id', '=', self.id),
                       ('sn_toll_receipt', '=', True)],
            'context': {'create': False},
        }

    def action_view_delivery_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Finished Goods Deliveries'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('sn_toll_order_id', '=', self.id),
                       ('sn_toll_delivery', '=', True)],
            'context': {'create': False},
        }


class SnTollMaterialLine(models.Model):
    """Material the customer supplies for a toll manufacturing order."""

    _name = 'sn.toll.material.line'
    _description = 'Toll Manufacturing Supplied Material'
    _check_company_auto = True
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'sn.toll.order', string='Toll Manufacturing Order', required=True,
        ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    company_id = fields.Many2one(
        'res.company', string='Company', related='order_id.company_id',
        store=True, readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency', related='order_id.currency_id',
        readonly=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Material', required=True,
        check_company=True, ondelete='restrict',
    )
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit', store=True, readonly=True,
        related='product_id.uom_id',
    )
    product_uom_qty = fields.Float(
        string='Supplied Quantity', required=True, digits='Product Unit',
        help='Quantity the customer announces as supplied. The receipt '
             'transfer is created for the quantity still missing.',
    )
    bom_line_id = fields.Many2one(
        'mrp.bom.line', string='Bill of Materials Line',
        check_company=True,
        domain="[('product_id', '=', product_id)]",
    )
    qty_received = fields.Float(
        string='Received', compute='_compute_quantities', digits='Product Unit',
        compute_sudo=True,
    )
    qty_consumed = fields.Float(
        string='Consumed', compute='_compute_quantities', digits='Product Unit',
        compute_sudo=True,
    )
    qty_theoretical = fields.Float(
        string='Theoretical Consumption', compute='_compute_quantities',
        digits='Product Unit', compute_sudo=True,
    )
    qty_loss = fields.Float(
        string='Loss', compute='_compute_quantities', digits='Product Unit',
        compute_sudo=True,
        help='Quantity consumed above the theoretical consumption plus the '
             'allowed loss tolerance. Only this quantity is settled with the '
             'customer.',
    )
    qty_to_receive = fields.Float(
        string='To Receive', compute='_compute_quantities', digits='Product Unit',
        compute_sudo=True,
    )
    qty_on_hand = fields.Float(
        string='In Stock', compute='_compute_quantities', compute_sudo=True,
        digits='Product Unit',
        help='Quantity of this material currently stored for the customer.',
    )

    @api.depends(
        'product_id', 'bom_line_id', 'product_uom_qty',
        'order_id.product_qty',
        'order_id.loss_allowance',
        'order_id.state',
        'order_id.production_ids.state',
        'order_id.production_ids.qty_produced',
        'order_id.material_picking_ids.state',
        'order_id.material_picking_ids.move_line_ids',
    )
    def _compute_quantities(self):
        for line in self:
            order = line.order_id
            received = 0.0
            for picking in order.material_picking_ids.filtered(
                    lambda picking: picking.state == 'done'):
                for move_line in picking.move_line_ids:
                    if move_line.product_id == line.product_id:
                        received += move_line.quantity
            consumed = 0.0
            for move in order.production_ids.move_raw_ids.filtered(
                    lambda move: move.product_id == line.product_id):
                if move.state == 'done':
                    consumed += move.quantity
                else:
                    consumed += sum(
                        move_line.quantity for move_line in move.move_line_ids)
            produced = sum(order.production_ids.mapped('qty_produced'))
            # The bill of materials line is optional on the supplied material
            # line: fall back to the line of the order bill of materials that
            # carries the same product, otherwise the theoretical consumption
            # would be zero and every consumed unit would look like a loss.
            bom_line = line.bom_line_id
            if not bom_line and order.bom_id:
                bom_line = order.bom_id.bom_line_ids.filtered(
                    lambda candidate: candidate.product_id == line.product_id,
                )[:1]
            unit_qty = bom_line.product_qty if bom_line else 0.0
            bom_qty = order.bom_id.product_qty or 1.0
            theoretical = unit_qty * (produced or order.product_qty) / bom_qty
            tolerance = theoretical * order.loss_allowance / 100.0
            loss = max(consumed - theoretical - tolerance, 0.0)
            on_hand = 0.0
            if order.partner_id:
                quants = self.env['stock.quant'].sudo().search([
                    ('product_id', '=', line.product_id.id),
                    ('owner_id', '=', order.partner_id.id),
                    ('location_id.usage', 'in', ('internal', 'transit')),
                    ('company_id', '=', order.company_id.id),
                ])
                on_hand = sum(quants.mapped('quantity'))
            line.qty_received = received
            line.qty_consumed = consumed
            line.qty_theoretical = theoretical
            line.qty_loss = loss
            line.qty_to_receive = max(line.product_uom_qty - received, 0.0)
            line.qty_on_hand = on_hand
