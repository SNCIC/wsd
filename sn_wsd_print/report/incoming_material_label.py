from markupsafe import Markup

from odoo import _, models
from odoo.exceptions import UserError


class ReportIncomingMaterialLabelZpl(models.AbstractModel):
    _name = 'report.sn_wsd_print.report_incoming_material_label_zpl'
    _description = 'Incoming Material Label ZPL Report'

    @staticmethod
    def _clean_zpl_text(value):
        text = str(value or '').replace('^', ' ').replace('~', ' ')
        return ' '.join(text.split())

    def _get_report_values(self, docids, data=None):
        lots = self.env['stock.lot'].browse(docids).exists()
        if not lots:
            raise UserError(_('No material lots were selected for label printing.'))
        for lot in lots:
            lot.label_print_count += 1
        labels = []
        for lot in lots:
            labels.append({
                'material_code': Markup(self._clean_zpl_text(lot.product_id.default_code)),
                'material_name': Markup(self._clean_zpl_text(lot.product_id.name)),
                'specification': Markup(self._clean_zpl_text(lot.product_id.material_specification)),
                'supplier_code': Markup(self._clean_zpl_text(lot.supplier_code)),
                'supplier_name': Markup(self._clean_zpl_text(lot.supplier_name)),
                'batch_no': Markup(self._clean_zpl_text(lot.supplier_batch_no)),
                'quantity': Markup(self._clean_zpl_text(lot.initial_quantity)),
                'material_sn': Markup(self._clean_zpl_text(lot.name)),
                'qr_data': Markup(self._clean_zpl_text(lot.name)),
            })
        return {
            'doc_ids': lots.ids,
            'doc_model': 'stock.lot',
            'docs': lots,
            'labels': labels,
        }
