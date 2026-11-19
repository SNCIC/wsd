from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class TollCustomerPortal(CustomerPortal):

    def _get_toll_order_domain(self):
        partner = request.env.user.partner_id
        return [('partner_id', '=', partner.commercial_partner_id.id)]

    @http.route(
        ['/my/toll/orders', '/my/toll/orders/page/<int:page>'],
        type='http', auth='user', website=True,
    )
    def portal_my_toll_orders(self, page=1, **kwargs):
        order_model = request.env['sn.toll.order']
        domain = self._get_toll_order_domain()
        order_count = order_model.search_count(domain)
        pager = portal_pager(
            url='/my/toll/orders',
            total=order_count,
            page=page,
            step=self._items_per_page,
        )
        orders = order_model.search(
            domain,
            order='date_order desc, id desc',
            limit=self._items_per_page,
            offset=pager['offset'],
        )
        values = {
            'orders': orders,
            'page_name': 'toll_orders',
            'pager': pager,
            'default_url': '/my/toll/orders',
        }
        return request.render('sn_wsd_toll.portal_my_toll_orders', values)

    @http.route(['/my/toll/orders/<int:order_id>'],
                type='http', auth='user', website=True)
    def portal_my_toll_order_detail(self, order_id, **kwargs):
        order = request.env['sn.toll.order'].browse(order_id).exists()
        if not order or (
            order.partner_id.commercial_partner_id
            != request.env.user.partner_id.commercial_partner_id
        ):
            raise request.not_found()
        values = {
            'order': order,
            'page_name': 'toll_order',
        }
        return request.render('sn_wsd_toll.portal_my_toll_order_detail', values)
