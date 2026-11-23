from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare


class StockMove(models.Model):
    _inherit = 'stock.move'

    sn_bill_line_ids = fields.One2many(
        comodel_name='account.move.line',
        inverse_name='sn_stock_move_id',
        string='Bill Lines',
        copy=False,
    )
    sn_invoiced_qty = fields.Float(
        string='Billed Quantity',
        compute='_compute_sn_bill_quantities',
        store=True,
        digits='Product Unit',
        help="Quantity of this receipt line already billed to the vendor.",
    )
    sn_to_bill_qty = fields.Float(
        string='Quantity to Bill',
        compute='_compute_sn_bill_quantities',
        store=True,
        digits='Product Unit',
        help="Quantity received and still waiting for a vendor bill.",
    )
    sn_bill_status = fields.Selection(
        selection=[
            ('to_bill', 'To Bill'),
            ('partial', 'Partially Billed'),
            ('billed', 'Billed'),
            ('closed', 'Billing Closed'),
        ],
        string='Billing Status',
        compute='_compute_sn_bill_status',
        store=True,
        help="Billing state of the receipt line. A line is closed by hand when "
             "no bill is expected from the vendor.",
    )
    sn_bill_names = fields.Char(
        string='Vendor Bills',
        compute='_compute_sn_bill_names',
        help="Vendor bills that consumed this receipt line.",
    )
    sn_billing_closed = fields.Boolean(
        string='Billing Closed',
        copy=False,
        help="Set when the receipt line is not billed on purpose: free samples "
             "or goods the vendor does not invoice.",
    )
    sn_billing_close_date = fields.Date(
        string='Billing Close Date',
        copy=False,
        readonly=True,
    )
    sn_billing_close_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Billing Closed by',
        copy=False,
        readonly=True,
    )

    @api.depends(
        'quantity',
        'state',
        'product_uom',
        'sn_bill_line_ids.quantity',
        'sn_bill_line_ids.product_uom_id',
        'sn_bill_line_ids.display_type',
        'sn_bill_line_ids.move_id.state',
        'sn_bill_line_ids.move_id.move_type',
    )
    def _compute_sn_bill_quantities(self):
        for move in self:
            billed = 0.0
            for line in move.sn_bill_line_ids:
                if line.display_type not in (False, 'product') or line.move_id.state == 'cancel':
                    continue
                qty = line.quantity
                if line.move_id.move_type == 'in_refund':
                    qty = -qty
                if line.product_uom_id and move.product_uom and line.product_uom_id != move.product_uom:
                    qty = line.product_uom_id._compute_quantity(
                        qty, move.product_uom, rounding_method='HALF-UP')
                billed += qty
            move.sn_invoiced_qty = billed
            remaining = move.quantity - billed if move.state == 'done' else 0.0
            move.sn_to_bill_qty = max(remaining, 0.0)

    @api.depends(
        'sn_invoiced_qty',
        'sn_to_bill_qty',
        'state',
        'sn_billing_closed',
        'purchase_line_id',
    )
    def _compute_sn_bill_status(self):
        for move in self:
            if move.sn_billing_closed:
                move.sn_bill_status = 'closed'
                continue
            if move.state != 'done' or not move.purchase_line_id:
                move.sn_bill_status = False
                continue
            rounding = move.product_uom.rounding or 0.01
            if float_compare(move.sn_invoiced_qty, 0.0, precision_rounding=rounding) <= 0:
                move.sn_bill_status = 'to_bill'
            elif float_compare(move.sn_to_bill_qty, 0.0, precision_rounding=rounding) > 0:
                move.sn_bill_status = 'partial'
            else:
                move.sn_bill_status = 'billed'

    @api.depends(
        'sn_bill_line_ids.move_id.name',
        'sn_bill_line_ids.move_id.state',
    )
    def _compute_sn_bill_names(self):
        for move in self:
            names = move.sn_bill_line_ids.move_id.filtered(
                lambda move: move.state != 'cancel').mapped('name')
            move.sn_bill_names = ', '.join(sorted({name for name in names if name}))

    def action_sn_open_bill_wizard(self):
        """Open the billing wizard on the receipt lines selected in the list."""
        moves = self.filtered(
            lambda move: move.state == 'done' and move.sn_to_bill_qty > 0)
        if not moves:
            raise UserError(_("The selected receipt lines have nothing left to bill."))
        partners = moves.picking_id.partner_id
        if len(partners) != 1:
            raise UserError(_("Select the receipt lines of a single vendor."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Vendor Bill'),
            'res_model': 'sn.vendor.bill.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': partners.id,
                'default_picking_ids': [(6, 0, moves.picking_id.ids)],
                'default_date_mode': 'custom',
                'default_include_open_from_previous_periods': False,
            },
        }

    def action_sn_close_billing(self):
        """Stop billing the selected receipt lines without billing them.

        The line leaves the billing pool the same way it does in the vendor
        system this module follows: the quantity stays received, only the
        billing is closed.
        """
        moves = self.filtered(lambda move: move.state == 'done' and not move.sn_billing_closed)
        if not moves:
            raise UserError(_("Only done receipt lines can be closed for billing."))
        moves.write({
            'sn_billing_closed': True,
            'sn_billing_close_date': fields.Date.context_today(self),
            'sn_billing_close_user_id': self.env.user.id,
        })
        return True

    def action_sn_reopen_billing(self):
        moves = self.filtered('sn_billing_closed')
        moves.write({
            'sn_billing_closed': False,
            'sn_billing_close_date': False,
            'sn_billing_close_user_id': False,
        })
        return True

    def action_sn_view_bills(self):
        bills = self.sn_bill_line_ids.move_id
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', bills.ids)],
        }
        if len(bills) == 1:
            action.update({'view_mode': 'form', 'res_id': bills.id})
        return action
