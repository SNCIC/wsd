from odoo import fields, models


class SnWsdExceptionParetoWizard(models.TransientModel):
    _name = 'sn.wsd.exception.pareto.wizard'
    _description = 'SN WSD Exception Pareto Wizard'

    dimension = fields.Selection(
        [
            ('subcategory', 'Subcategory'),
            ('category', 'Category'),
            ('line', 'Production Line'),
            ('level', 'Level'),
        ],
        string='Dimension',
        required=True,
        default='subcategory',
    )
    date_from = fields.Date(string='From', default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(string='To', default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        # web version: open the rendered HTML report in a new browser tab
        # (no wkhtmltopdf involved; the browser's own print dialog can save a PDF)
        report = self.env.ref('sn_wsd_exception.action_report_exception_pareto')
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/%s/%s' % (report.report_name, self.id),
            'target': 'new',
        }
