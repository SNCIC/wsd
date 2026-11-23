from datetime import datetime, time

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class SnVendorBillWizard(models.TransientModel):
    _name = 'sn.vendor.bill.wizard'
    _description = 'Vendor Bill from Receipts'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Vendor',
        required=True,
        domain=[('supplier_rank', '>', 0)],
    )
    picking_ids = fields.Many2many(
        comodel_name='stock.picking',
        string='Receipts',
        help="Leave empty to bill every receipt of the vendor that matches the period.",
    )
    date_mode = fields.Selection(
        selection=[
            ('current_month', 'Current Month'),
            ('last_month', 'Last Month'),
            ('open', 'All Open Receipts'),
            ('custom', 'Custom Period'),
        ],
        string='Period',
        default='current_month',
        required=True,
    )
    date_from = fields.Date(string='Start Date')
    date_to = fields.Date(string='End Date')
    include_open_from_previous_periods = fields.Boolean(
        string='Include Open Receipts of Previous Periods',
        default=True,
        help="Bill the receipts of the period together with every older receipt "
             "still waiting for a bill. This is the cumulative mode of the "
             "vendor billing.",
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    line_ids = fields.One2many(
        comodel_name='sn.vendor.bill.wizard.line',
        inverse_name='wizard_id',
        string='Receipt Lines',
    )
    bill_amount = fields.Monetary(
        string='Total',
        compute='_compute_bill_amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_bill_amount',
    )

    @api.depends('company_id', 'partner_id', 'line_ids.subtotal', 'line_ids.selected')
    def _compute_bill_amount(self):
        for wizard in self:
            partner = wizard.partner_id
            purchase_currency = (
                partner.property_purchase_currency_id
                if 'property_purchase_currency_id' in partner._fields else False)
            wizard.currency_id = (
                purchase_currency
                or wizard.company_id.currency_id
                or self.env.company.currency_id)
            wizard.bill_amount = sum(
                wizard.line_ids.filtered('selected').mapped('subtotal'))

    @api.onchange('date_mode')
    def _onchange_date_mode(self):
        self._apply_date_mode()

    @api.onchange(
        'partner_id',
        'picking_ids',
        'date_from',
        'date_to',
        'include_open_from_previous_periods',
    )
    def _onchange_billable_lines(self):
        self._load_billable_lines()

    def _apply_date_mode(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.date_mode == 'current_month':
            self.date_from = today.replace(day=1)
            self.date_to = today.replace(day=1) + relativedelta(months=1, days=-1)
        elif self.date_mode == 'last_month':
            first_day = today.replace(day=1) - relativedelta(months=1)
            self.date_from = first_day
            self.date_to = first_day + relativedelta(months=1, days=-1)
        elif self.date_mode == 'open':
            self.date_from = False
            self.date_to = today
        # A custom period keeps the dates typed by the user.

    def _get_billable_domain(self):
        self.ensure_one()
        domain = [
            ('state', '=', 'done'),
            ('purchase_line_id', '!=', False),
            ('sn_to_bill_qty', '>', 0),
            ('company_id', 'in', self.env.companies.ids),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
        ]
        if self.picking_ids:
            domain.append(('picking_id', 'in', self.picking_ids.ids))
        else:
            domain.append(('picking_id.partner_id', '=', self.partner_id.id))
            if not self.include_open_from_previous_periods and self.date_from:
                domain.append(('picking_id.date_done', '>=', datetime.combine(self.date_from, time.min)))
            if self.date_to:
                domain.append(('picking_id.date_done', '<', datetime.combine(
                    self.date_to + relativedelta(days=1), time.min)))
        return domain

    def _get_billable_moves(self):
        self.ensure_one()
        return self.env['stock.move'].search(
            self._get_billable_domain(), order='date, id')

    def _prepare_line_vals(self, move):
        purchase_line = move.purchase_line_id
        return {
            'selected': True,
            'move_id': move.id,
            'received_qty': move.quantity,
            'to_bill_qty': move.sn_to_bill_qty,
            'quantity': move.sn_to_bill_qty,
            'price_unit': purchase_line.price_unit,
        }

    def _load_billable_lines(self):
        self.ensure_one()
        commands = [Command.clear()]
        for move in self._get_billable_moves():
            commands.append(Command.create(self._prepare_line_vals(move)))
        self.line_ids = commands

    def action_load_lines(self):
        self.ensure_one()
        self._load_billable_lines()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_create_bill(self):
        """Create one vendor bill from the selected receipt lines."""
        self.ensure_one()
        lines = self.line_ids.filtered(
            lambda line: line.selected and float_compare(
                line.quantity, 0.0,
                precision_rounding=line.product_uom_id.rounding or 0.01) > 0)
        if not lines:
            raise UserError(_("Select at least one receipt line to bill."))
        moves = lines.move_id
        if len(moves.company_id) > 1:
            raise UserError(_("The selected receipt lines belong to several companies."))
        # Lock the receipt lines so that two users cannot bill the same quantity.
        self.env.cr.execute(
            'SELECT id FROM stock_move WHERE id IN %s FOR UPDATE',
            (tuple(moves.ids),))
        moves.invalidate_recordset(['sn_invoiced_qty', 'sn_to_bill_qty'])
        for line in lines:
            rounding = line.product_uom_id.rounding or 0.01
            if float_compare(line.quantity, line.move_id.sn_to_bill_qty, precision_rounding=rounding) > 0:
                raise UserError(_(
                    "%(product)s of %(receipt)s has only %(available)s left to bill.",
                    product=line.product_id.display_name,
                    receipt=line.picking_id.display_name,
                    available=line.move_id.sn_to_bill_qty,
                ))
        orders = moves.purchase_line_id.order_id
        currencies = orders.currency_id
        if len(currencies) > 1:
            raise UserError(_("The selected receipt lines are ordered in several currencies."))
        currency = currencies[:1] or self.company_id.currency_id
        pickings = moves.picking_id
        invoice_line_ids = [
            Command.create(line._prepare_account_move_line_vals())
            for line in lines
        ]
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_id.id,
            'currency_id': currency.id,
            'company_id': self.company_id.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_origin': ', '.join(sorted(set(pickings.mapped('name')))),
            'invoice_payment_term_id': self.partner_id.property_supplier_payment_term_id.id or False,
            'invoice_line_ids': invoice_line_ids,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Bill'),
            'res_model': 'account.move',
            'res_id': bill.id,
            'view_mode': 'form',
            'target': 'current',
        }


class SnVendorBillWizardLine(models.TransientModel):
    _name = 'sn.vendor.bill.wizard.line'
    _description = 'Vendor Bill Wizard Line'
    _order = 'date_done, move_id'

    wizard_id = fields.Many2one(
        comodel_name='sn.vendor.bill.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    selected = fields.Boolean(string='Select', default=True)
    move_id = fields.Many2one(
        comodel_name='stock.move',
        string='Receipt Move',
        required=True,
        ondelete='cascade',
    )
    picking_id = fields.Many2one(
        comodel_name='stock.picking',
        string='Receipt',
        related='move_id.picking_id',
    )
    date_done = fields.Datetime(
        string='Receipt Date',
        related='move_id.picking_id.date_done',
    )
    purchase_order_id = fields.Many2one(
        comodel_name='purchase.order',
        string='Purchase Order',
        related='move_id.purchase_line_id.order_id',
    )
    purchase_request_names = fields.Char(
        string='Purchase Requests',
        compute='_compute_purchase_request_names',
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        related='move_id.product_id',
    )
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unit of Measure',
        related='move_id.product_uom',
    )
    received_qty = fields.Float(
        string='Received Quantity',
        digits='Product Unit',
        readonly=True,
    )
    to_bill_qty = fields.Float(
        string='Quantity to Bill',
        digits='Product Unit',
        readonly=True,
    )
    quantity = fields.Float(
        string='Billed Quantity',
        digits='Product Unit',
    )
    price_unit = fields.Float(
        string='Unit Price',
        digits='Product Price',
    )
    subtotal = fields.Monetary(
        string='Subtotal',
        compute='_compute_subtotal',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='wizard_id.currency_id',
    )

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.depends('move_id')
    def _compute_purchase_request_names(self):
        for line in self:
            requests = line.move_id.purchase_request_ids
            if not requests and 'purchase_request_lines' in line.move_id.purchase_line_id._fields:
                requests = line.move_id.purchase_line_id.purchase_request_lines.request_id
            names = requests.mapped('name')
            line.purchase_request_names = ', '.join(sorted({name for name in names if name}))

    def _prepare_account_move_line_vals(self):
        """Bill line values of the receipt line, keeping the purchase order line.

        The purchase line is kept on the bill line so that the standard billed
        quantity of the order stays in sync, the receipt line is added next to
        it to give the bill its receipt.
        """
        self.ensure_one()
        purchase_line = self.move_id.purchase_line_id
        values = purchase_line._prepare_account_move_line()
        values.update({
            'quantity': self.quantity,
            'price_unit': self.price_unit,
            'sn_stock_move_id': self.move_id.id,
            'name': '%s - %s' % (
                values.get('name') or self.product_id.display_name,
                self.picking_id.name or '',
            ),
        })
        return values
