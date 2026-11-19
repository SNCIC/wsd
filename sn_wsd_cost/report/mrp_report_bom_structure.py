from odoo import api, fields, models


class ReportMrpReportBomStructure(models.AbstractModel):
    """Cost the BoM overview on the latest purchase prices.

    The standard report prices every component with the standard cost of the
    product. Here the price of a purchased component is the latest confirmed
    purchase price of the material, carried with its purchase date and its
    vendor, so the cost of the BoM and the dates it is built on are visible in
    the same screen. A semi-finished component keeps its manufacturing cost,
    which is the sum of the costs of its own components and operations.
    """

    _inherit = 'report.mrp.report_bom_structure'

    @api.model
    def get_html(self, bom_id=False, searchQty=1, searchVariant=False):
        res = super().get_html(bom_id, searchQty, searchVariant)
        res['has_cost_info'] = self._has_cost_info(res['lines'])
        return res

    @api.model
    def _get_pdf_doc(self, bom_id, data, quantity, product_variant_id=None):
        doc = super()._get_pdf_doc(bom_id, data, quantity, product_variant_id)
        doc['has_cost_info'] = self._has_cost_info(doc)
        return doc

    @api.model
    def _has_cost_info(self, data):
        """Whether the price and purchase date columns carry a value."""
        if data.get('sn_cost_source') == 'purchase':
            return True
        return any(
            self._has_cost_info(component)
            for component in data.get('components', [])
        )

    @api.model
    def _get_bom_data(self, bom, warehouse, product=False, line_qty=False, bom_line=False,
                      level=0, parent_bom=False, parent_product=False, index=0,
                      product_info=False, ignore_stock=False,
                      simulated_leaves_per_workcenter=False):
        res = super()._get_bom_data(
            bom, warehouse, product, line_qty, bom_line, level, parent_bom, parent_product,
            index, product_info, ignore_stock, simulated_leaves_per_workcenter,
        )
        # A product carrying its own BoM is costed by manufacturing, not by a
        # purchase price: the columns stay empty on its line.
        res['sn_unit_cost'] = False
        res['sn_cost_date'] = ''
        res['sn_cost_partner'] = ''
        res['sn_cost_source'] = 'manufacture' if level else False
        return res

    @api.model
    def _get_component_data(self, parent_bom, parent_product, warehouse, bom_line, line_quantity,
                            level, index, product_info, ignore_stock=False):
        res = super()._get_component_data(
            parent_bom, parent_product, warehouse, bom_line, line_quantity, level, index,
            product_info, ignore_stock,
        )
        company = parent_bom.company_id or self.env.company
        product = bom_line.product_id.with_company(company)
        uom = bom_line.product_uom_id or product.uom_id
        cost = product._sn_get_cost_in_uom(uom)
        price = company.currency_id.round(cost['price'] * line_quantity)
        res['bom_cost'] = price
        res['sn_unit_cost'] = cost['price']
        res['sn_cost_date'] = fields.Date.to_string(cost['date']) if cost['date'] else ''
        res['sn_cost_source'] = cost['source']
        res['sn_cost_partner'] = cost['partner_id'].display_name or ''
        return res

    @api.model
    def _get_bom_array_lines(self, data, level, unfolded_ids, unfolded, parent_unfolded=True):
        lines = super()._get_bom_array_lines(data, level, unfolded_ids, unfolded, parent_unfolded)
        self._set_line_costs(lines, 0, data)
        return lines

    @api.model
    def _set_line_costs(self, lines, position, data):
        """Copy the cost of each component on its flat PDF line.

        The parent builds one line per component, directly followed by the lines
        of the components of that sub-BoM, hence the cursor. The operations and
        byproducts rows are appended after the components and need no value.
        """
        for component in data.get('components', []):
            if position >= len(lines):
                return position
            lines[position]['sn_unit_cost'] = component.get('sn_unit_cost')
            lines[position]['sn_cost_date'] = component.get('sn_cost_date', '')
            lines[position]['sn_cost_source'] = component.get('sn_cost_source')
            position += 1
            if component.get('components'):
                position = self._set_line_costs(lines, position, component)
        return position
