"""Editable Word (.docx) output of the purchase contracts.

The reports are declared as regular ``ir.actions.report`` records of the module,
so they show up in the Print menu of the purchase order next to the PDF
contracts. The web client has no converter for the ``docx`` type: the download
is streamed by ``controllers/report_download.py`` on request of the handler
registered in ``static/src/js/office_report_handler.js``.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..report.purchase_contract_document import (
    FLAVOUR_DEFAULT,
    FLAVOUR_XINPENG,
)

# Contract flavour rendered by each Word report of the module.
DOCX_FLAVOURS = {
    'sn_wsd_purchase.report_purchase_contract_default_docx': FLAVOUR_DEFAULT,
    'sn_wsd_purchase.report_purchase_contract_docx': FLAVOUR_XINPENG,
}


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    report_type = fields.Selection(selection_add=[
        ('docx', 'DOCX'),
    ], ondelete={'docx': 'set default'})

    @api.model
    def _render_docx(self, report_ref, docids, data=None):
        """Render the Word contract of the records `docids`."""
        report = self._get_report(report_ref)
        docs = self.env[report.model].browse(docids)
        flavour = DOCX_FLAVOURS.get(report.report_name, FLAVOUR_DEFAULT)
        try:
            from ..report.purchase_contract_docx import (
                build_purchase_contract_docx)
            content = build_purchase_contract_docx(docs, flavour)
        except ImportError:
            raise UserError(self.env._(
                "The DOCX export requires the python-docx library. Install it "
                "on the server: pip install python-docx"))
        return content, 'docx'
