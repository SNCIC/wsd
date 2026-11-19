from odoo import fields, models


class MrpProduction(models.Model):
    """Data of the dot-matrix production order sheet.

    The sheet is the task the workshop receives: the product to make, the
    quantity and the dates it runs between, in one band of the 135 mm form.
    """

    _name = 'mrp.production'
    _inherit = ['mrp.production', 'sn.prn.mixin']

    def _sn_get_production_order_prn_data(self):
        """Fields of the sheet, read once for the drawing."""
        self.ensure_one()
        product = self.product_id
        return {
            'workshop': self.x_workshop_id.display_name or '',
            'date': self._sn_prn_date(self.create_date),
            'name': self.name or '',
            'product_code': product.default_code or '',
            'product_name': product.name or '',
            'material_specification': product.material_specification or '',
            'uom': self.product_uom_id.name or '',
            'quantity': self._sn_prn_number(self.product_qty),
            'date_start': self._sn_prn_date(self.date_start),
            'date_deadline': self._sn_prn_date(self.date_deadline),
            'note': self.sn_prn_note or '',
            'released_by': self.sn_prn_reviewer_id.name or '',
            'prepared_by': self.create_uid.name or '',
        }

    @staticmethod
    def _sn_prn_date(value):
        """Date of a datetime field as the sheet prints it."""
        return fields.Datetime.to_datetime(value).strftime('%Y-%m-%d') if value else ''

    def action_print_production_order_prn(self):
        """Download the ESC/P stream of the production order sheet."""
        return self._sn_prn_action('/sn_wsd_mrp/production_order/prn')
