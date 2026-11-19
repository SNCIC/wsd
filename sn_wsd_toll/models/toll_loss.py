from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import float_compare


class SnTollLoss(models.Model):
    """Settlement of the material consumed above the tolerated quantity.

    Three settlement types are supported, all of them kept on the same
    document so the customer statement lists them consistently:

    * ``deduct``: the amount is deducted from the processing fee invoice;
    * ``claim``: a separate draft customer invoice is created;
    * ``resupply``: a consignment receipt records the material the customer
      sends back to cover the loss.
    """

    _name = 'sn.toll.loss'
    _description = 'Toll Manufacturing Loss Settlement'
    _inherit = ['mail.thread']
    _check_company_auto = True
    _order = 'date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default='/', index=True,
    )
    order_id = fields.Many2one(
        'sn.toll.order', string='Toll Manufacturing Order', required=True,
        ondelete='cascade', index=True, tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Customer', store=True, readonly=True,
        related='order_id.partner_id',
    )
    company_id = fields.Many2one(
        'res.company', string='Company', store=True, readonly=True,
        related='order_id.company_id',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency', store=True, readonly=True,
        related='order_id.currency_id',
    )
    date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today,
    )
    settlement_type = fields.Selection(
        selection=[
            ('deduct', 'Deduct from Processing Fee'),
            ('claim', 'Separate Claim Invoice'),
            ('resupply', 'Customer Resupply'),
        ],
        string='Settlement Type', required=True, default='deduct',
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('done', 'Settled'),
            ('cancel', 'Cancelled'),
        ],
        string='Status', default='draft', required=True, copy=False,
        tracking=True, index=True,
    )
    line_ids = fields.One2many(
        'sn.toll.loss.line', 'loss_id', string='Loss Lines', copy=True,
    )
    amount = fields.Monetary(
        string='Total Amount', currency_field='currency_id',
        compute='_compute_amount', store=True,
    )
    account_move_id = fields.Many2one(
        'account.move', string='Claim Invoice', readonly=True, copy=False,
        check_company=True,
    )
    picking_id = fields.Many2one(
        'stock.picking', string='Resupply Receipt', readonly=True,
        copy=False, check_company=True,
    )
    note = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('sn.toll.loss')
                    or '/')
        return super().create(vals_list)

    @api.depends('line_ids.amount')
    def _compute_amount(self):
        for loss in self:
            loss.amount = sum(loss.line_ids.mapped('amount'))

    def action_generate_lines(self):
        """Fill the lines with the loss of every supplied material."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_(
                "Loss settlement '%s' is not a draft.", self.display_name))
        self.line_ids.unlink()
        commands = []
        for line in self.order_id.material_line_ids:
            if float_compare(
                    line.qty_loss, 0.0,
                    precision_rounding=line.product_id.uom_id.rounding) <= 0:
                continue
            commands.append(Command.create({
                'product_id': line.product_id.id,
                'product_uom_id': line.product_id.uom_id.id,
                'quantity': line.qty_loss,
                'unit_cost': line.product_id.standard_price,
            }))
        if not commands:
            raise UserError(_(
                "Toll manufacturing order '%s' has no material loss above "
                "the tolerated quantity.", self.order_id.display_name))
        self.write({'line_ids': commands})
        return True

    def action_confirm(self):
        for loss in self.filtered(lambda loss: loss.state == 'draft'):
            if not loss.line_ids:
                raise UserError(_(
                    "Loss settlement '%s' has no line.", loss.display_name))
            if loss.settlement_type == 'claim':
                loss._create_claim_invoice()
            elif loss.settlement_type == 'resupply':
                loss._create_resupply_receipt()
            else:
                loss._apply_sale_deduction()
            loss.write({'state': 'done'})
        return True

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def _apply_sale_deduction(self):
        """Deduct the loss from the processing fee.

        When the toll manufacturing order comes from a sale order, the
        deduction is added as a negative line so the invoice billed from that
        sale order carries it. Standalone toll orders keep the deduction on
        the toll order itself: their invoice subtracts it directly.
        """
        self.ensure_one()
        order = self.order_id
        if not order.sale_order_id:
            return
        if not order.fee_product_id:
            raise UserError(_(
                "Select the processing fee product on toll manufacturing "
                "order '%s' so the loss can be deducted on sale order '%s'.",
                order.display_name, order.sale_order_id.display_name))
        self.env['sale.order.line'].create([{
            'order_id': order.sale_order_id.id,
            'product_id': order.fee_product_id.id,
            'name': _(
                'Loss deduction - %(order)s - %(loss)s',
                order=order.name, loss=self.name),
            'product_uom_qty': 1.0,
            'price_unit': -line.amount,
            'tax_ids': [Command.clear()],
        } for line in self.line_ids])

    def _create_claim_invoice(self):
        self.ensure_one()
        if self.account_move_id:
            return self.account_move_id
        lines = [Command.create({
            'product_id': line.product_id.id,
            'name': _(
                'Material loss - %(order)s - %(product)s',
                order=self.order_id.name,
                product=line.product_id.display_name),
            'quantity': line.quantity,
            'price_unit': line.unit_cost,
        }) for line in self.line_ids]
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'invoice_date': self.date,
            'invoice_origin': '%s / %s' % (self.order_id.name, self.name),
            'sn_toll_order_id': self.order_id.id,
            'invoice_line_ids': lines,
        })
        self.account_move_id = move
        return move

    def _create_resupply_receipt(self):
        self.ensure_one()
        if self.picking_id:
            return self.picking_id
        order = self.order_id
        warehouse = order._get_warehouse()
        picking_type = order._get_consignment_picking_type(warehouse)
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'partner_id': order.partner_id.id,
            'owner_id': order.partner_id.id,
            'location_id': order._get_supplier_location().id,
            'location_dest_id': warehouse.lot_stock_id.id,
            'origin': '%s / %s' % (order.name, self.name),
            'company_id': order.company_id.id,
            'sn_toll_order_id': order.id,
            'sn_toll_receipt': True,
        })
        for line in self.line_ids:
            self.env['stock.move'].create({
                'product_id': line.product_id.id,
                'product_uom': line.product_uom_id.id,
                'product_uom_qty': line.quantity,
                'picking_id': picking.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'company_id': order.company_id.id,
                'restrict_partner_id': order.partner_id.id,
            })
        picking.action_confirm()
        self.picking_id = picking
        return picking

    def action_view_account_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Claim Invoice'),
            'res_model': 'account.move',
            'res_id': self.account_move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Resupply Receipt'),
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class SnTollLossLine(models.Model):
    _name = 'sn.toll.loss.line'
    _description = 'Toll Manufacturing Loss Line'
    _check_company_auto = True

    loss_id = fields.Many2one(
        'sn.toll.loss', string='Loss Settlement', required=True,
        ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company', store=True, readonly=True,
        related='loss_id.company_id',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency', store=True, readonly=True,
        related='loss_id.currency_id',
    )
    product_id = fields.Many2one(
        'product.product', string='Material', required=True,
        check_company=True, ondelete='restrict',
    )
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit', required=True,
    )
    quantity = fields.Float(
        string='Lost Quantity', required=True, digits='Product Unit',
    )
    unit_cost = fields.Monetary(
        string='Unit Cost', currency_field='currency_id',
        help='Value of one lost unit, used by the claim invoice and by the '
             'deduction from the processing fee. Defaults to the material '
             'cost and can be negotiated with the customer.',
    )
    amount = fields.Monetary(
        string='Amount', currency_field='currency_id',
        compute='_compute_amount', store=True,
    )

    @api.depends('quantity', 'unit_cost')
    def _compute_amount(self):
        for line in self:
            line.amount = line.quantity * line.unit_cost
