from odoo import _, models
from odoo.exceptions import UserError


class ReportIssueMaterialLabelZpl(models.AbstractModel):
    """Issue material labels rendered by the label-center engine.

    The layout lives in the seed template
    ``sn_wsd_stock.label_template_issue_material``; it reuses the incoming
    material layout but is bound to stock.move.line, because the quantity to
    print is the issued quantity carried by the operation. This report only
    keeps the same entry-point contract as the incoming one: docids
    validation, one print-audit line per operation and a single ``zpl`` string
    for the qweb-text shell.

    Because the report is also bound to stock.move.line (Print menu), it
    re-applies the eligibility gate: electronic reel materials and lines with
    nothing issued are skipped instead of failing the whole selection.
    """

    _name = 'report.sn_wsd_stock.report_issue_material_label_zpl'
    _description = 'Issue Material Label ZPL Report'

    def _get_report_values(self, docids, data=None):
        selected = self.env['stock.move.line'].browse(docids).exists()
        lines = selected.filtered(
            lambda line: line._is_issue_material_label_candidate()).sorted(
                key=lambda line: (
                    line.picking_id.name or '',
                    line.product_id.default_code or '',
                    line.lot_id.name or '',
                    line.id,
                )
        )
        if not lines:
            raise UserError(_(
                'Nothing to print: no tracked non-reel material operation '
                'with an issued quantity was selected.'))
        template = self.env.ref('sn_wsd_stock.label_template_issue_material')
        renderer = self.env['sn.label.renderer']
        zpl = renderer.render_zpl(template._to_layout_dict(), lines)
        self._log_print(template, lines)
        return {'zpl': zpl}

    def _log_print(self, template, lines):
        """One sn.label.print.log per printed operation, written with sudo so
        printing never requires write access on the audit model."""
        company_id = template.company_id.id or self.env.company.id
        self.env['sn.label.print.log'].sudo().create([{
            'template_id': template.id,
            'res_model': lines._name,
            'res_id': line.id,
            'copies': 1,
            'user_id': self.env.user.id,
            'company_id': company_id,
        } for line in lines])
