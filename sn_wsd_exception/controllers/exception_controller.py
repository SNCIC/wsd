from odoo import fields, http
from odoo.http import request


class SnWsdExceptionController(http.Controller):
    """Jsonrpc endpoints consumed by shop-floor terminals + the Pareto web page."""

    @http.route('/sn_wsd_exception/pareto', type='http', auth='user', website=False)
    def pareto_page(self, dimension='subcategory', date_from=None, date_to=None, **kwargs):
        report = request.env['report.sn_wsd_exception.report_exception_pareto']
        if dimension not in ('subcategory', 'category', 'line', 'level'):
            dimension = 'subcategory'
        if not date_from:
            date_from = fields.Date.today().replace(day=1)
        if not date_to:
            date_to = fields.Date.context_today(request.env.user)
        rows, total = report._get_pareto_rows(dimension, date_from, date_to)
        return request.render('sn_wsd_exception.pareto_page', {
            'dimension': dimension,
            'date_from': date_from,
            'date_to': date_to,
            'rows': rows,
            'total': total,
        })

    def _ticket_data(self, ticket):
        return {
            'id': ticket.id,
            'name': ticket.name,
            'state': ticket.state,
            'category_id': ticket.category_id.id,
            'category_name': ticket.category_id.display_name,
            'level': ticket.level,
        }

    @http.route('/sn_wsd_exception/get_categories', type='jsonrpc', auth='user')
    def get_categories(self):
        categories = request.env['sn.wsd.exception.category'].search([
            ('parent_id', '=', False),
            ('active', '=', True),
        ], order='sequence, id')
        return [{
            'id': category.id,
            'name': category.display_name,
            'code': category.code or '',
            'default_team_id': category.default_team_id.id or False,
            'default_level': category.default_level or 'normal',
        } for category in categories]

    @http.route('/sn_wsd_exception/create_exception', type='jsonrpc', auth='user')
    def create_exception(self, line_id, category_id, note, image_base64=None,
                         reported_by_user_id=None, mes_order_id=None, repeat_of_id=None):
        service = request.env['sn.wsd.exception.service']
        return service.report(
            line_id=line_id,
            category_id=category_id,
            note=note,
            image_base64=image_base64,
            reported_by_id=reported_by_user_id,
            mes_order_id=mes_order_id,
            repeat_of_id=repeat_of_id,
        )

    @http.route('/sn_wsd_exception/get_open_exceptions', type='jsonrpc', auth='user')
    def get_open_exceptions(self, line_id=None, workshop_id=None):
        service = request.env['sn.wsd.exception.service']
        return service.open_list(line_id=line_id, workshop_id=workshop_id)

    @http.route('/sn_wsd_exception/claim_exception', type='jsonrpc', auth='user')
    def claim_exception(self, ticket_id):
        service = request.env['sn.wsd.exception.service']
        return service.claim(ticket_id)
