from odoo import api, fields, models

# Item rows of the material issue and return sheets: a band of the 135 mm form
# carries six materials, a longer picking continues on the next band.
SN_MES_MATERIAL_ROWS = 6
SN_MES_MATERIAL_DETAIL_ROWS = 8


class StockPicking(models.Model):
    """Data of the MES material issue and return sheets."""

    _name = 'stock.picking'
    _inherit = ['stock.picking', 'sn.prn.mixin']

    sn_prn_mes_issue = fields.Boolean(
        string='Material Issue',
        compute='_compute_sn_prn_mes_operation',
        store=True,
        help='The transfer issues material to a workshop: it is printed on '
             'the material issue sheet.',
    )
    sn_prn_mes_return = fields.Boolean(
        string='Material Return',
        compute='_compute_sn_prn_mes_operation',
        store=True,
        help='The transfer returns material to the stock: it is printed on '
             'the material return sheet.',
    )

    @api.depends('picking_type_id')
    def _compute_sn_prn_mes_operation(self):
        for picking in self:
            picking_type = picking.picking_type_id
            warehouse = picking_type.warehouse_id
            picking.sn_prn_mes_issue = bool(
                warehouse and picking_type in (
                    warehouse.picking_type_issue_id
                    | warehouse.picking_type_over_pick_id))
            picking.sn_prn_mes_return = bool(
                warehouse
                and picking_type == warehouse.picking_type_return_id)

    def _sn_get_mes_material_moves(self):
        """Moves reported on the sheet, in the order of the paper form."""
        self.ensure_one()
        return self.move_ids.filtered(
            lambda move: move.state != 'cancel' and move.product_id
        ).sorted(lambda move: (move.sequence, move.id))

    def _sn_get_mes_material_department(self):
        """Department of the workshop the goods go to or come from.

        The MES order the picking was generated from carries the workshop of
        its production line; the department is that workshop, printed on the
        head of both sheets.
        """
        self.ensure_one()
        return self.x_mes_order_id.x_workshop_id.display_name or ''

    def _sn_get_mes_material_product(self):
        """Finished product the MES order issues the material for."""
        self.ensure_one()
        return self.x_mes_order_id.product_id

    def _sn_get_mes_issue_prn_lines(self):
        """Rows of the material issue sheet, one per issued material."""
        self.ensure_one()
        rows = []
        for index, move in enumerate(self._sn_get_mes_material_moves(),
                                     start=1):
            rows.append({
                'sequence': index,
                'product_code': move.product_id.default_code or '',
                'product_name': move.product_id.name or '',
                'material_specification':
                    move.product_id.material_specification or '',
                'uom': move.product_uom.name or '',
                'quantity': self._sn_prn_number(move.quantity),
            })
        return rows

    def _sn_get_mes_issue_prn_pages(self):
        """Split the rows of the issue sheet into the bands of the form."""
        self.ensure_one()
        rows = self._sn_get_mes_issue_prn_lines()
        start = range(0, max(len(rows), 1), SN_MES_MATERIAL_ROWS)
        return [rows[index:index + SN_MES_MATERIAL_ROWS] for index in start]

    def _sn_get_mes_issue_prn_detail_lines(self):
        """Rows of the detailed issue sheet, with demand and issued quantity.

        The detailed sheet is printed when the workshop needs the quantity
        asked for next to the quantity delivered, the product the material is
        issued for and the code of the material replaced when there is one.
        """
        self.ensure_one()
        rows = []
        for index, move in enumerate(self._sn_get_mes_material_moves(),
                                     start=1):
            rows.append({
                'sequence': index,
                'product_code': move.product_id.default_code or '',
                'product_name': move.product_id.name or '',
                'material_specification':
                    move.product_id.material_specification or '',
                'uom': move.product_uom.name or '',
                'demand_quantity': self._sn_prn_number(move.product_uom_qty),
                'quantity': self._sn_prn_number(move.quantity),
                # The paper form has a column for the code of the material the
                # workshop used before the substitution; the stock does not
                # keep it, so the column stays empty but keeps its place.
                'old_code': '',
            })
        return rows

    def _sn_get_mes_issue_prn_detail_pages(self):
        """Split the detailed rows into the bands of the form."""
        self.ensure_one()
        rows = self._sn_get_mes_issue_prn_detail_lines()
        start = range(0, max(len(rows), 1), SN_MES_MATERIAL_DETAIL_ROWS)
        return [rows[index:index + SN_MES_MATERIAL_DETAIL_ROWS]
                for index in start]

    def _sn_get_mes_return_prn_lines(self):
        """Rows of the material return sheet, one per returned material."""
        self.ensure_one()
        rows = []
        for index, move in enumerate(self._sn_get_mes_material_moves(),
                                     start=1):
            rows.append({
                'sequence': index,
                'product_code': move.product_id.default_code or '',
                'product_name': move.product_id.name or '',
                'material_specification':
                    move.product_id.material_specification or '',
                'uom': move.product_uom.name or '',
                'quantity': self._sn_prn_number(move.quantity),
            })
        return rows

    def _sn_get_mes_return_prn_pages(self):
        """Split the rows of the return sheet into the bands of the form."""
        self.ensure_one()
        rows = self._sn_get_mes_return_prn_lines()
        start = range(0, max(len(rows), 1), SN_MES_MATERIAL_ROWS)
        return [rows[index:index + SN_MES_MATERIAL_ROWS] for index in start]

    def _sn_get_mes_material_prn_total(self):
        """Total quantity of the picking, printed in the total row."""
        self.ensure_one()
        total = sum(self._sn_get_mes_material_moves().mapped('quantity'))
        return self._sn_prn_number(total, 4)

    def action_print_mes_issue_prn(self):
        """Download the ESC/P stream of the material issue sheet."""
        return self._sn_prn_action('/sn_wsd_mrp/mes_issue/prn')

    def action_print_mes_issue_detail_prn(self):
        """Download the ESC/P stream of the detailed material issue sheet."""
        return self._sn_prn_action('/sn_wsd_mrp/mes_issue_detail/prn')

    def action_print_mes_return_prn(self):
        """Download the ESC/P stream of the material return sheet."""
        return self._sn_prn_action('/sn_wsd_mrp/mes_return/prn')
