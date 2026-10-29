from odoo import api, fields, models


class StockPicking(models.Model):
    """Inspection request printed on the receipt of a three-step reception.

    The first step of the reception (vendors -> input) hands the goods over to
    the quality control. The sheet printed on that receipt travels with the
    goods, is signed by the warehouse keeper and by the inspector, and marks
    the materials no incoming inspection scheme covers as waived.

    The lines follow the operation lines of the moves so that the supplier
    batch read on the goods is printed on its own row. The receipt of a
    three-step reception does not record that batch (it is read at putaway),
    so the column stays empty there, ready to be filled in by hand.
    """

    _inherit = 'stock.picking'

    sn_is_reception_receipt = fields.Boolean(
        string='Reception Receipt',
        compute='_compute_sn_is_reception_receipt',
        help='Receipt of a three-step reception: the operation the inspection '
             'request is printed on.',
    )
    sn_inspection_request_reviewer_id = fields.Many2one(
        'res.users',
        string='Inspection Request Reviewer',
        default=lambda self: self.env.user,
        help='Person who reviews the inspection request printed on the '
             'receipt.',
    )

    @api.depends('picking_type_id')
    def _compute_sn_is_reception_receipt(self):
        for picking in self:
            picking.sn_is_reception_receipt = picking._sn_is_reception_receipt()

    def _sn_is_reception_receipt(self):
        """Whether the transfer is the receipt of a three-step reception.

        The quality control and storage operation types only exist once the
        reception is set to three steps, so the receipt is told apart from the
        other incoming operations by the operation type of its warehouse.
        """
        self.ensure_one()
        picking_type = self.picking_type_id
        warehouse = picking_type.warehouse_id
        if not warehouse or warehouse.reception_steps != 'three_steps':
            return False
        return picking_type == warehouse.in_type_id

    def _sn_get_inspection_request_warehouse_name(self):
        self.ensure_one()
        return self.picking_type_id.warehouse_id.name or ''

    def _sn_is_move_inspection_waived(self, move):
        """Whether the incoming inspection waives the material of the move.

        A material is waived when no effective incoming inspection scheme
        covers it: the same rule that keeps the incoming quality control from
        creating an inspection for it.
        """
        self.ensure_one()
        inspection_model = self.env['sn.wsd.quality.inspection'].with_company(
            self.company_id or self.env.company)
        scheme = inspection_model._find_scheme(
            'iqc',
            product=move.product_id,
            move_line=move.move_line_ids[:1],
        )
        return not scheme

    def _sn_get_inspection_request_lines(self):
        """Rows of the inspection request: one per operation line of the moves."""
        self.ensure_one()
        lines = []
        sequence = 0
        warehouse_name = self._sn_get_inspection_request_warehouse_name()
        moves = self.move_ids.filtered(
            lambda move: move.state != 'cancel' and move.product_id
        ).sorted(lambda move: (move.sequence, move.id))
        for move in moves:
            waived = self._sn_is_move_inspection_waived(move)
            operation_lines = move.move_line_ids.filtered(
                lambda line: line.quantity or line.lot_name or line.lot_id
                or line.supplier_batch_no
            ).sorted('id')
            if not operation_lines:
                sequence += 1
                lines.append(self._sn_prepare_inspection_request_line(
                    sequence, move, self.env['stock.move.line'],
                    warehouse_name, waived))
                continue
            for operation_line in operation_lines:
                sequence += 1
                lines.append(self._sn_prepare_inspection_request_line(
                    sequence, move, operation_line, warehouse_name, waived))
        return lines

    def _sn_prepare_inspection_request_line(
            self, sequence, move, operation_line, warehouse_name, waived):
        product = move.product_id
        quantity = (
            operation_line.quantity
            if operation_line
            else (move.quantity or move.product_uom_qty)
        )
        return {
            'sequence': sequence,
            'product_code': product.default_code or '',
            'product_name': product.name or '',
            'material_specification': product.material_specification or '',
            'weight': self._sn_format_inspection_request_number(product.weight),
            'lot_name': (
                operation_line.supplier_batch_no
                or operation_line.lot_name
                or operation_line.lot_id.name
                or ''
            ),
            'uom': move.product_uom.name or '',
            'quantity': self._sn_format_inspection_request_number(quantity),
            'warehouse': warehouse_name,
            'origin': self.origin or '',
            'waived': waived,
        }

    @api.model
    def _sn_format_inspection_request_number(self, value):
        """Print a quantity without the trailing zeros of the float type."""
        text = ('%.6f' % (value or 0.0)).rstrip('0').rstrip('.')
        return text or '0'

    def _sn_is_inspection_request_waived(self, lines=None):
        """Whether every row of the inspection request is waived."""
        self.ensure_one()
        lines = self._sn_get_inspection_request_lines() if lines is None else lines
        return bool(lines) and all(line['waived'] for line in lines)
