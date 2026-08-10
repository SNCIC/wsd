from markupsafe import Markup

from odoo import models, _
from odoo.exceptions import UserError


LABEL_POSITIONS = (
    {'x': 18, 'y': 15},
    {'x': 314, 'y': 15},
    {'x': 18, 'y': 86},
    {'x': 314, 'y': 86},
)


class ReportInternalSerialLabelZpl(models.AbstractModel):
    _name = 'report.sn_wsd_print.report_internal_serial_label_zpl'
    _description = 'Internal Serial Label ZPL Report'

    @staticmethod
    def _clean_zpl_text(value):
        text = str(value or '').replace('^', ' ').replace('~', ' ')
        return ' '.join(text.split())

    def _get_report_values(self, docids, data=None):
        serials = self.env['sn.wsd.internal.serial'].browse(docids).exists()
        if not serials:
            raise UserError(_('No internal serials were selected for label printing.'))
        if 'label_print_count' in serials._fields:
            self.env.cr.execute(
                '''
                UPDATE sn_wsd_internal_serial
                   SET label_print_count = COALESCE(label_print_count, 0) + 1
                 WHERE id = ANY(%s)
                ''',
                [serials.ids],
            )
            serials.invalidate_recordset(['label_print_count'])

        labels = []
        for serial in serials:
            serial_no = self._clean_zpl_text(serial.serial_no)
            labels.append({
                'serial_no': Markup(serial_no),
                'barcode_data': Markup(serial_no),
            })

        sheets = []
        for index in range(0, len(labels), len(LABEL_POSITIONS)):
            sheet = []
            for position, label in zip(LABEL_POSITIONS, labels[index:index + len(LABEL_POSITIONS)]):
                sheet.append({
                    **position,
                    **label,
                })
            sheets.append(sheet)

        return {
            'doc_ids': serials.ids,
            'doc_model': 'sn.wsd.internal.serial',
            'docs': serials,
            'sheets': sheets,
        }
