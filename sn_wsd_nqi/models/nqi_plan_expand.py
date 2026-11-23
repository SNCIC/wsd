"""NQI production plan expansion: header bring-in from the sales order
and detail expansion over the MTO chain.

Level mapping (see design decision 5): the NQI plan header maps to the
sales order line (task level), details map to manufacturing orders
(which carry the product kind and the SN segment); MES orders are the
execution layer and produce no NQI plan rows.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'


class NqiPtPlan(models.Model):
    _inherit = 'sn.wsd.nqi.pt.plan'

    detail_ids = fields.One2many(
        'sn.wsd.nqi.pt.plan.detail', 'plan_id', string='Plan Details')

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        for record in self:
            order = record.sale_order_id
            if not order:
                continue
            values = {'plan_code': order.name}
            if order.date_order:
                values['start_time'] = order.date_order.strftime(
                    DATETIME_FORMAT)
            lines = order.order_line.filtered(lambda line: line.product_id)
            if lines:
                product = lines[0].product_id
                values['product_code'] = product.default_code
            for field_name, value in values.items():
                if value and not record[field_name]:
                    record[field_name] = value

    def action_expand_details(self):
        """(Re)build the detail lines from the sales order MTO chain.

        One detail row per manufacturing order: TYPE from the product
        board/machine kind (01 meter / 02 PCB), COUNT from the order
        quantity, SN segment bounds from the order segment fields.
        """
        for record in self:
            if not record.sale_order_id:
                raise UserError(_(
                    'Pick a sales order before expanding details.'))
            orders = record._nqi_manufacturing_orders()
            if not orders:
                raise UserError(_(
                    'No manufacturing order found under sales order %s '
                    '(check the MTO chain).',
                    record.sale_order_id.display_name))
            Detail = self.env['sn.wsd.nqi.pt.plan.detail']
            Detail.search([('plan_id', '=', record.id)]).unlink()
            for production in orders:
                kind = production.product_id._nqi_product_kind()
                Detail.create({
                    'plan_id': record.id,
                    'plan_code': record.plan_code,
                    'count': str(int(production.product_qty or 0)),
                    'type': {'machine': '01', 'board': '02'}.get(kind, ''),
                    'start_serial_no': production.x_sn_segment_start or '',
                    'finish_serial_no': production.x_sn_segment_end or '',
                })
        return True

    def _nqi_manufacturing_orders(self):
        """Manufacturing orders under the sales order (MTO chain)."""
        self.ensure_one()
        order = self.sale_order_id
        domains = []
        if order.procurement_group_id:
            domains.append([
                ('procurement_group_id', '=', order.procurement_group_id.id)])
        if order.name:
            domains.append([('origin', '=', order.name)])
        if not domains:
            return self.env['mrp.production']
        domain = domains[0]
        for extra in domains[1:]:
            domain = ['|'] + domain + extra
        return self.env['mrp.production'].search(domain)


class NqiPtPlanDetail(models.Model):
    _inherit = 'sn.wsd.nqi.pt.plan.detail'

    plan_id = fields.Many2one(
        'sn.wsd.nqi.pt.plan', string='NQI Plan', index=True,
        ondelete='cascade')
