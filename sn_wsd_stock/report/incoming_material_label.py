from odoo import _, models
from odoo.exceptions import UserError


class ReportIncomingMaterialLabelZpl(models.AbstractModel):
    """Incoming material labels rendered by the label-center engine.

    The layout lives in the seed template
    ``sn_wsd_stock.label_template_incoming_material`` (sn.label.template +
    elements); this report only keeps the entry-point contract of the former
    hardcoded-ZPL report: docids validation, ``label_print_count``
    bookkeeping, one print-audit line per lot and a single ``zpl`` string
    for the qweb-text shell.
    """

    _name = 'report.sn_wsd_stock.report_incoming_material_label_zpl'
    _description = 'Incoming Material Label ZPL Report'

    def _get_report_values(self, docids, data=None):
        lots = self.env['stock.lot'].browse(docids).exists().sorted(
            key=lambda lot: (lot.material_sn_base or lot.name or '', lot.id)
        )
        if not lots:
            raise UserError(_('No material lots were selected for label printing.'))
        for lot in lots:
            lot.label_print_count += 1

        template = self.env.ref('sn_wsd_stock.label_template_incoming_material')
        renderer = self.env['sn.label.renderer']
        zpl = renderer.render_zpl(template._to_layout_dict(), lots)
        self._log_print(template, lots)
        return {'zpl': zpl}

    def _log_print(self, template, lots):
        """One sn.label.print.log per printed lot, written with sudo so
        printing never requires write access on the audit model."""
        company_id = template.company_id.id or self.env.company.id
        self.env['sn.label.print.log'].sudo().create([{
            'template_id': template.id,
            'res_model': lots._name,
            'res_id': lot.id,
            'copies': 1,
            'user_id': self.env.user.id,
            'company_id': company_id,
        } for lot in lots])
