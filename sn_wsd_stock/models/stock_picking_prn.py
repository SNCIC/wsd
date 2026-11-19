from odoo import api, fields, models

# Item rows of the other receipt and the other delivery sheets: a band of the
# 135 mm form carries six materials, the same count as ITEM_ROWS of
# report/other_operation_prn.py.
SN_OTHER_OPERATION_ROWS = 6


class StockPicking(models.Model):
    """Data of the dot-matrix other receipt and other delivery sheets.

    The two sheets are printed from the transfers of the other warehouse
    operation types; the picking already carries the department, the employee
    and the operation type the sheets print, so only the rows of the item table
    and the print actions live here.
    """

    _name = 'stock.picking'
    _inherit = ['stock.picking', 'sn.prn.mixin']

    sn_prn_other_receipt = fields.Boolean(
        string='Other Receipt Sheet',
        compute='_compute_sn_prn_other_operation',
        store=True,
        help='The transfer is an other receipt: it is printed on the other '
             'receipt sheet.',
    )
    sn_prn_other_delivery = fields.Boolean(
        string='Other Delivery Sheet',
        compute='_compute_sn_prn_other_operation',
        store=True,
        help='The transfer is an other delivery: it is printed on the other '
             'delivery sheet.',
    )

    @api.depends('sn_other_operation')
    def _compute_sn_prn_other_operation(self):
        for picking in self:
            picking.sn_prn_other_receipt = (
                picking.sn_other_operation == 'other_in')
            picking.sn_prn_other_delivery = (
                picking.sn_other_operation == 'other_out')

    def _sn_get_other_operation_prn_moves(self):
        """Moves reported on the sheet, in the order of the paper form."""
        self.ensure_one()
        return self.move_ids.filtered(
            lambda move: move.state != 'cancel' and move.product_id
        ).sorted(lambda move: (move.sequence, move.id))

    def _sn_get_other_operation_prn_lines(self):
        """Rows of the item table, one per received or delivered material."""
        self.ensure_one()
        # The remark of the sheet belongs to the document, not to a line: it is
        # written on the first row of the table, as the paper form does.
        note = self.sn_prn_note or self.note or ''
        rows = []
        for index, move in enumerate(
                self._sn_get_other_operation_prn_moves(), start=1):
            rows.append({
                'sequence': index,
                'product_code': move.product_id.default_code or '',
                'product_name': move.product_id.name or '',
                'material_specification':
                    move.product_id.material_specification or '',
                'uom': move.product_uom.name or '',
                'quantity': self._sn_prn_number(move.quantity),
                'note': note if index == 1 else '',
            })
        return rows

    def _sn_get_other_operation_prn_pages(self):
        """Split the item rows into the bands of the continuous form."""
        self.ensure_one()
        rows = self._sn_get_other_operation_prn_lines()
        start = range(0, max(len(rows), 1), SN_OTHER_OPERATION_ROWS)
        return [rows[index:index + SN_OTHER_OPERATION_ROWS] for index in start]

    def _sn_get_other_operation_prn_total(self):
        """Total quantity of the transfer, printed in the total row."""
        self.ensure_one()
        total = sum(self._sn_get_other_operation_prn_moves().mapped('quantity'))
        return self._sn_prn_number(total, 6)

    def action_print_other_receipt_prn(self):
        """Download the ESC/P stream of the other receipt for the bridge."""
        return self._sn_prn_action('/sn_wsd_stock/other_receipt/prn')

    def action_print_other_delivery_prn(self):
        """Download the ESC/P stream of the other delivery for the bridge."""
        return self._sn_prn_action('/sn_wsd_stock/other_delivery/prn')
