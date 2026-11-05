from odoo import api, models


class ReportMrpReportBomStructure(models.AbstractModel):
    """Show the material specification of the products in the BoM overview.

    The overview and its PDF export render the same data, so the specification
    is carried by every BOM and component line. The column is only displayed
    when at least one line of the structure has a specification, the way the
    attachments column behaves.
    """

    _inherit = 'report.mrp.report_bom_structure'

    @api.model
    def get_html(self, bom_id=False, searchQty=1, searchVariant=False):
        res = super().get_html(bom_id, searchQty, searchVariant)
        res['has_specifications'] = self._has_specifications(res['lines'])
        return res

    @api.model
    def _get_pdf_doc(self, bom_id, data, quantity, product_variant_id=None):
        doc = super()._get_pdf_doc(bom_id, data, quantity, product_variant_id)
        doc['has_specifications'] = self._has_specifications(doc)
        return doc

    @api.model
    def _has_specifications(self, data):
        return bool(data.get('material_specification')) or any(
            self._has_specifications(component) for component in data.get('components', [])
        )

    @api.model
    def _get_bom_data(self, bom, warehouse, product=False, line_qty=False, bom_line=False, level=0,
                      parent_bom=False, parent_product=False, index=0, product_info=False,
                      ignore_stock=False, simulated_leaves_per_workcenter=False):
        res = super()._get_bom_data(
            bom, warehouse, product, line_qty, bom_line, level, parent_bom, parent_product,
            index, product_info, ignore_stock, simulated_leaves_per_workcenter,
        )
        bom_product = res.get('product') or bom.product_tmpl_id.product_variant_id
        res['material_specification'] = bom_product.product_tmpl_id.material_specification or ''
        return res

    @api.model
    def _get_component_data(self, parent_bom, parent_product, warehouse, bom_line, line_quantity,
                            level, index, product_info, ignore_stock=False):
        res = super()._get_component_data(
            parent_bom, parent_product, warehouse, bom_line, line_quantity, level, index,
            product_info, ignore_stock,
        )
        res['material_specification'] = bom_line.product_id.material_specification or ''
        return res

    @api.model
    def _get_bom_array_lines(self, data, level, unfolded_ids, unfolded, parent_unfolded=True):
        lines = super()._get_bom_array_lines(data, level, unfolded_ids, unfolded, parent_unfolded)
        self._set_line_specifications(lines, 0, data)
        return lines

    @api.model
    def _set_line_specifications(self, lines, position, data):
        """Copy the specification of each component on its flat PDF line.

        The parent builds one line per component, directly followed by the lines
        of the components of that sub-BOM, hence the cursor. The operations and
        byproducts rows are appended after the components and need no value.
        """
        for component in data.get('components', []):
            if position >= len(lines):
                return position
            lines[position]['material_specification'] = component.get('material_specification', '')
            position += 1
            if component.get('components'):
                position = self._set_line_specifications(lines, position, component)
        return position
