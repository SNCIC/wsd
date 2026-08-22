from odoo import _, api, models

from .exception_category import LEVEL_SELECTION

DIMENSION_SELECTION = [
    ('subcategory', 'Subcategory'),
    ('category', 'Category'),
    ('line', 'Production Line'),
    ('level', 'Level'),
]


class ReportSnWsdExceptionPareto(models.AbstractModel):
    _name = 'report.sn_wsd_exception.report_exception_pareto'
    _description = 'SN WSD Exception Pareto Report'

    def _dimension_label(self, ticket, dimension):
        if dimension == 'subcategory':
            value = ticket.subcategory_id or ticket.category_id
            return value.display_name
        if dimension == 'category':
            return ticket.category_id.display_name
        if dimension == 'line':
            return ticket.production_line_id.display_name
        if dimension == 'level':
            return dict(LEVEL_SELECTION).get(ticket.level, ticket.level or 'N/A')
        return 'N/A'

    @api.model
    def _get_pareto_rows(self, dimension, date_from=False, date_to=False):
        """Shared statistics: returns (rows, total) sorted descending."""
        self = self.with_context(lang=self.env.user.lang)
        domain = [
            ('state', '!=', 'cancelled'),
            ('company_id', 'in', self.env.companies.ids or [self.env.company.id]),
        ]
        if date_from:
            domain.append(('reported_at', '>=', f'{date_from} 00:00:00'))
        if date_to:
            domain.append(('reported_at', '<=', f'{date_to} 23:59:59'))
        tickets = self.env['sn.wsd.exception.ticket'].search(domain)

        counter = {}
        for ticket in tickets:
            label = self._dimension_label(ticket, dimension)
            counter[label] = counter.get(label, 0) + 1

        total = sum(counter.values())
        rows = []
        cumulative = 0.0
        for rank, (label, count) in enumerate(
            sorted(counter.items(), key=lambda item: item[1], reverse=True), start=1
        ):
            share = count / total * 100.0 if total else 0.0
            cumulative += share
            rows.append({
                'rank': rank,
                'label': label,
                'count': count,
                'share': share,
                'cumulative': cumulative,
            })
        return rows, total

    def _get_report_values(self, docids, data=None):
        docs = self.env['sn.wsd.exception.pareto.wizard'].browse(docids)
        wizard = docs[0] if docs else self.env['sn.wsd.exception.pareto.wizard']
        rows, total = self._get_pareto_rows(wizard.dimension, wizard.date_from, wizard.date_to)
        return {
            'doc_ids': docids,
            'doc_model': 'sn.wsd.exception.pareto.wizard',
            'docs': docs,
            'rows': rows,
            'total': total,
            'dimension_label': _(dict(DIMENSION_SELECTION).get(wizard.dimension, wizard.dimension)),
        }
