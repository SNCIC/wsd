from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class AccountMove(models.Model):
    _inherit = 'account.move'

    sn_picking_ids = fields.Many2many(
        comodel_name='stock.picking',
        string='Receipts',
        compute='_compute_sn_receipt_info',
        help="Purchase receipts billed by this vendor bill.",
    )
    sn_picking_count = fields.Integer(
        string='Receipt Count',
        compute='_compute_sn_receipt_info',
    )
    sn_purchase_request_ids = fields.Many2many(
        comodel_name='purchase.request',
        string='Purchase Requests',
        compute='_compute_sn_receipt_info',
        help="Purchase requests behind the receipts billed by this vendor bill.",
    )
    sn_purchase_request_count = fields.Integer(
        string='Purchase Request Count',
        compute='_compute_sn_receipt_info',
    )

    @api.depends(
        'line_ids.sn_stock_move_id',
        'line_ids.sn_stock_move_id.picking_id',
        'line_ids.purchase_line_id',
    )
    def _compute_sn_receipt_info(self):
        for move in self:
            bill_lines = move.line_ids.filtered('sn_stock_move_id')
            pickings = bill_lines.sn_stock_move_id.picking_id
            requests = bill_lines.sn_stock_move_id.purchase_request_ids
            if not requests:
                requests = bill_lines.purchase_line_id.purchase_request_lines.request_id
            move.sn_picking_ids = pickings
            move.sn_picking_count = len(pickings)
            move.sn_purchase_request_ids = requests
            move.sn_purchase_request_count = len(requests)

    def action_sn_view_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Receipts'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.sn_picking_ids.ids)],
        }

    def action_sn_view_purchase_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Requests'),
            'res_model': 'purchase.request',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.sn_purchase_request_ids.ids)],
        }

    def action_post(self):
        """Refuse to post a vendor bill that bills more than what was received."""
        self.filtered(
            lambda move: move.move_type in ('in_invoice', 'in_refund')
        ).line_ids._check_sn_stock_move_qty()
        return super().action_post()


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    sn_stock_move_id = fields.Many2one(
        comodel_name='stock.move',
        string='Receipt Move',
        ondelete='restrict',
        index='btree_not_null',
        copy=False,
        check_company=True,
        help="Receipt line this bill line consumes. It keeps the billed quantity "
             "of the receipt and links the bill back to its receipt.",
    )
    sn_picking_id = fields.Many2one(
        comodel_name='stock.picking',
        string='Receipt',
        related='sn_stock_move_id.picking_id',
        store=True,
        readonly=True,
    )
    sn_purchase_request_names = fields.Char(
        string='Purchase Requests',
        compute='_compute_sn_purchase_request_names',
        help="Purchase requests behind the receipt line of this bill line.",
    )

    @api.depends('sn_stock_move_id', 'purchase_line_id')
    def _compute_sn_purchase_request_names(self):
        for line in self:
            requests = line.sn_stock_move_id.purchase_request_ids
            if not requests and 'purchase_request_lines' in line.purchase_line_id._fields:
                requests = line.purchase_line_id.purchase_request_lines.request_id
            names = requests.mapped('name')
            line.sn_purchase_request_names = ', '.join(sorted({name for name in names if name}))

    @api.constrains('sn_stock_move_id', 'quantity', 'product_uom_id', 'move_id')
    def _check_sn_stock_move_qty(self):
        """Keep the billed quantity of a receipt line within the received quantity."""
        bill_lines = self.filtered(
            lambda line: line.sn_stock_move_id
            and line.display_type in (False, 'product')
            and line.move_id.state != 'cancel')
        for move in bill_lines.sn_stock_move_id:
            rounding = move.product_uom.rounding or 0.01
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
            if float_compare(billed, move.quantity, precision_rounding=rounding) > 0:
                raise ValidationError(_(
                    "The billed quantity of %(product)s exceeds the received "
                    "quantity of %(receipt)s.",
                    product=move.product_id.display_name,
                    receipt=move.picking_id.display_name or move.reference,
                ))
