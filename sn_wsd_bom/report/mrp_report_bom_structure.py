from odoo import api, models
from odoo.addons.sn_wsd_mrp.models.mrp_bom_line_qty import fraction_from_qty


class ReportMrpReportBomStructure(models.AbstractModel):
    """Show the material specification and the usage fraction of the BoM lines.

    The overview and its PDF export render the same data, so the specification
    is carried by every BOM and component line. The column is only displayed
    when at least one line of the structure has a specification, the way the
    attachments column behaves.

    The usage of a component is expressed by the ERP as a numerator over a
    denominator, which is the source of the quantity. Both values are carried
    by every BOM and component line and shown as their own columns, right
    before the quantity they expand to.
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
        # The top-level product is not a component line and has no usage
        # fraction. A sub-BoM keeps the fraction of the line it is reached by.
        res['qty_numerator'] = bom_line.qty_numerator if bom_line else False
        res['qty_denominator'] = bom_line.qty_denominator if bom_line else False
        return res

    @api.model
    def _get_component_data(self, parent_bom, parent_product, warehouse, bom_line, line_quantity,
                            level, index, product_info, ignore_stock=False):
        res = super()._get_component_data(
            parent_bom, parent_product, warehouse, bom_line, line_quantity, level, index,
            product_info, ignore_stock,
        )
        res['material_specification'] = bom_line.product_id.material_specification or ''
        res['qty_numerator'] = bom_line.qty_numerator
        res['qty_denominator'] = bom_line.qty_denominator
        return res

    @api.model
    def _get_bom_array_lines(self, data, level, unfolded_ids, unfolded, parent_unfolded=True):
        lines = super()._get_bom_array_lines(data, level, unfolded_ids, unfolded, parent_unfolded)
        self._set_line_specifications(lines, 0, data)
        self._set_line_fractions(lines, 0, data)
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

    @api.model
    def _merge_components(self, component_1, component_2):
        """Recompute the usage fraction when two lines are merged.

        The overview merges the components sharing the same product and unit of
        measure and sums their quantity, so the fraction of the first line alone
        would not match the merged quantity any more.
        """
        super()._merge_components(component_1, component_2)
        if component_1.get('qty_numerator'):
            component_1['qty_numerator'], component_1['qty_denominator'] = fraction_from_qty(
                component_1['quantity'])

    @api.model
    def _set_line_fractions(self, lines, position, data):
        """Copy the usage fraction of each component on its flat PDF line.

        Same cursor rule as ``_set_line_specifications``: the parent builds one
        line per component, directly followed by the lines of the components of
        that sub-BOM. The operations and byproducts rows have no fraction.
        """
        for component in data.get('components', []):
            if position >= len(lines):
                return position
            lines[position]['qty_numerator'] = component.get('qty_numerator')
            lines[position]['qty_denominator'] = component.get('qty_denominator')
            position += 1
            if component.get('components'):
                position = self._set_line_fractions(lines, position, component)
        return position
