from odoo import api, fields, models, _


class StockPicking(models.Model):
    _inherit = 'stock.picking'

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
        help="Billing state of the purchase lines received by this transfer.",
    )
    sn_bill_ids = fields.Many2many(
        comodel_name='account.move',
        string='Vendor Bills',
        compute='_compute_sn_bill_info',
    )
    sn_bill_count = fields.Integer(
        string='Vendor Bill Count',
        compute='_compute_sn_bill_info',
    )

    @api.depends('move_ids.sn_bill_status', 'move_ids.purchase_line_id', 'state')
    def _compute_sn_bill_status(self):
        for picking in self:
            moves = picking.move_ids.filtered('purchase_line_id')
            statuses = {status for status in moves.mapped('sn_bill_status') if status}
            if not moves:
                picking.sn_bill_status = False
            elif statuses == {'to_bill'}:
                picking.sn_bill_status = 'to_bill'
            elif statuses and statuses <= {'billed', 'closed'} and 'billed' in statuses:
                picking.sn_bill_status = 'billed'
            elif statuses == {'closed'}:
                picking.sn_bill_status = 'closed'
            else:
                picking.sn_bill_status = 'partial'

    @api.depends('move_ids', 'move_ids.sn_bill_line_ids', 'move_ids.sn_bill_line_ids.move_id.state')
    def _compute_sn_bill_info(self):
        for picking in self:
            bills = picking.move_ids.sn_bill_line_ids.move_id.filtered(
                lambda bill: bill.state != 'cancel')
            picking.sn_bill_ids = bills
            picking.sn_bill_count = len(bills)

    def action_sn_create_bill(self):
        """Open the billing wizard on the receipts of this transfer."""
        self.ensure_one()
        if self.sn_bill_status in (False, 'billed', 'closed'):
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Vendor Bill'),
            'res_model': 'sn.vendor.bill.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_picking_ids': [(6, 0, self.ids)],
                'default_date_mode': 'custom',
                'default_include_open_from_previous_periods': False,
            },
        }

    def action_sn_view_bills(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.sn_bill_ids.ids)],
        }
