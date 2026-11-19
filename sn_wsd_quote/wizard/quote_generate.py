from odoo import fields, models

# Depth guard of the BoM explosion: a BoM loop would otherwise never end.
MAX_BOM_LEVEL = 12


class SnWsdQuoteGenerate(models.TransientModel):
    """Fill the cost lines of a quotation estimate from a bill of materials.

    The materials are exploded down to the purchased components: every leaf
    becomes a material line carrying the quantity it takes to build one unit of
    the quoted product and the latest purchase price of the material. The
    operations are read from the process route, priced by the piece rate of the
    product, and by the work-center cost when no piece rate is defined.
    """

    _name = 'sn.wsd.quote.generate'
    _description = 'Generate Quotation Estimate Cost'

    quote_id = fields.Many2one(
        comodel_name='sn.wsd.quote',
        string='Quotation Estimate',
        required=True,
        ondelete='cascade',
    )
    bom_id = fields.Many2one(
        comodel_name='mrp.bom',
        string='Bill of Materials',
        required=True,
    )
    route_id = fields.Many2one(
        comodel_name='sn.wsd.process.route',
        string='Process Route',
    )
    explode_sub_boms = fields.Boolean(
        string='Explode Sub-BoMs',
        default=True,
        help='Cost the materials of the sub-assemblies instead of the '
             'sub-assembly itself. Kits are always exploded.',
    )
    include_operations = fields.Boolean(
        string='Include Operations',
        default=True,
    )
    clear_existing = fields.Boolean(
        string='Replace Existing Lines',
        default=True,
        help='Remove the cost lines of the estimate before generating the new '
             'ones.',
    )

    def action_generate(self):
        self.ensure_one()
        quote = self.quote_id
        if self.clear_existing:
            quote.line_ids.unlink()
        vals_list = []
        self._explode_bom(self.bom_id, 1.0 / (self.bom_id.product_qty or 1.0),
                          vals_list)
        if self.include_operations and self.route_id:
            vals_list += self._operation_values(quote)
        self.env['sn.wsd.quote.line'].create(
            [dict(vals, quote_id=quote.id) for vals in vals_list])
        quote.write({
            'bom_id': self.bom_id.id,
            'route_id': self.route_id.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.wsd.quote',
            'res_id': quote.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # BoM explosion
    # ------------------------------------------------------------------
    def _explode_bom(self, bom, ratio, vals_list, level=0):
        """Append one material line per purchased component.

        ``ratio`` is the number of BoM cycles needed to build one unit of the
        quoted product.
        """
        if level > MAX_BOM_LEVEL:
            return
        quote = self.quote_id
        for line in bom.bom_line_ids.sorted(lambda line: (line.sequence, line.id)):
            product = line.product_id
            if not product:
                continue
            quantity = ratio * line.product_qty
            quantity = line.product_uom_id._compute_quantity(
                quantity, product.uom_id)
            child_bom = line.child_bom_id
            if child_bom and (child_bom.type == 'phantom' or self.explode_sub_boms):
                self._explode_bom(
                    child_bom, quantity / (child_bom.product_qty or 1.0),
                    vals_list, level + 1)
                continue
            cost = product.with_company(quote.company_id)._sn_get_cost_in_uom(
                product.uom_id)
            vals_list.append({
                'line_type': 'material',
                'sequence': 10 + len(vals_list),
                'product_id': product.id,
                'name': product.display_name,
                'uom_id': product.uom_id.id,
                'quantity': quantity,
                'loss_percent': 0.0,
                'unit_price': cost['price'],
                'price_date': cost['date'],
                'price_source': cost['source'],
                'is_fixed': False,
            })

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _operation_values(self, quote):
        """One operation line per operation of the process route.

        The price is the piece rate of the product at the operation. Without a
        piece rate the work-center hourly cost of the operation duration is
        used, which is the same basis as the BoM overview.
        """
        vals_list = []
        sequence = 500
        for route_operation in self.route_id.route_operation_ids.sorted(
                lambda operation: (operation.sequence, operation.id)):
            rate = self.env['sn.wsd.piece.rate'].search([
                ('company_id', '=', quote.company_id.id),
                ('product_id', '=', quote.product_id.id),
                ('operation_id', '=', route_operation.operation_id.id),
            ], limit=1)
            if rate:
                price = rate.price
            else:
                work_center = route_operation.workcenter_id
                price = (work_center.costs_hour or 0.0) \
                    * (route_operation.time_cycle_manual or 0.0) / 60.0
            vals_list.append({
                'line_type': 'operation',
                'sequence': sequence,
                'operation_id': route_operation.operation_id.id,
                'name': route_operation.name
                or route_operation.operation_id.name,
                'quantity': 1.0,
                'loss_percent': 0.0,
                'unit_price': price,
                'is_fixed': False,
            })
            sequence += 10
        return vals_list
