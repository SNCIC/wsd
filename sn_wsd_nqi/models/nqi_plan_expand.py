"""NQI production plan: sales-order-line header with NQI references and
detail expansion over the MTO chain.

Level mapping (design decision 5): the plan header maps to a sales
order line (task level) - PLAN_CODE defaults to "<sale order>-<line
position>"; details map to manufacturing orders, which carry the product
kind and the SN segment. MES orders are the execution layer and produce
no NQI plan rows.

MTO chain in this Odoo version: ``mrp.production.sale_line_id`` links a
top-level order to its sale line, and every order of the chain (boards
included) carries the sale order name in ``origin``. There is no
procurement group on the sale order or the manufacturing order.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
PRODUCT_KIND_TO_TYPE = {'machine': '01', 'board': '02'}


class SaleOrderLineNqi(models.Model):
    _inherit = 'sale.order.line'

    def _nqi_product_lines(self):
        """Product lines of the order, in display order."""
        return self.order_id.order_line.filtered('product_id').sorted(
            key=lambda line: (line.sequence, line.id))

    def _nqi_default_plan_code(self):
        """Default NQI plan code of the line: "<order>-<line position>".

        One product line per plan keeps the header's single PRODUCT_CODE
        unambiguous; single-product orders read "<order>-1".
        """
        self.ensure_one()
        lines = self._nqi_product_lines()
        return '%s-%d' % (self.order_id.name, lines.ids.index(self.id) + 1)


class NqiPtPlan(models.Model):
    _inherit = 'sn.wsd.nqi.pt.plan'

    sale_order_line_id = fields.Many2one(
        'sale.order.line', string='Sales Order Line', index=True,
        ondelete='set null',
        domain="[('order_id', '=', sale_order_id), "
               "('product_id', '!=', False)]",
        help='Task-level anchor: one NQI plan per sales order line.')
    product_detail_id = fields.Many2one(
        'sn.wsd.nqi.rd.product.detail', string='NQI Product Detail',
        ondelete='set null',
        help='NQI PRODUCT_CODE references the product detail record '
             '(R&D chapter); the column keeps its code as a snapshot.')
    bidding_ids = fields.Many2many(
        'sn.wsd.nqi.pr.bidding.info', string='NQI Bidding Info',
        help='Framework contracts of the plan; their codes are joined '
             'into BUSINESS_CONTRACT_CODE.')
    detail_ids = fields.One2many(
        'sn.wsd.nqi.pt.plan.detail', 'plan_id', string='Plan Details')

    def _nqi_apply_line(self, line):
        """Fill the header from a sales order line.

        Returns the problems found (no or several NQI product details),
        so callers can raise them as a form warning.
        """
        self.ensure_one()
        notes = []
        self.plan_code = line._nqi_default_plan_code()
        details = self.env['sn.wsd.nqi.rd.product.detail'].search(
            [('product_id', '=', line.product_id.id)])
        if len(details) == 1:
            self.product_detail_id = details
            self.product_code = details.product_detail_code
        else:
            self.product_detail_id = False
            self.product_code = False
            notes.append(_(
                'No single NQI product detail for %(product)s: pick one '
                'on the plan, or maintain it under R&D first.',
                product=line.product_id.display_name))
        return notes

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        for record in self:
            order = record.sale_order_id
            if not order:
                record.sale_order_line_id = False
                continue
            if order.date_order and not record.start_time:
                record.start_time = order.date_order.strftime(
                    DATETIME_FORMAT)
            lines = order.order_line._nqi_product_lines()
            if len(lines) == 1 and not record.sale_order_line_id:
                # single-product order: the line needs no choice
                record.sale_order_line_id = lines
                record._nqi_apply_line(lines)

    @api.onchange('sale_order_line_id')
    def _onchange_sale_order_line_id(self):
        notes = []
        for record in self:
            if record.sale_order_line_id:
                notes += record._nqi_apply_line(record.sale_order_line_id)
        if notes:
            return {'warning': {
                'title': _('NQI product detail'),
                'message': ' '.join(notes),
                'type': 'warning',
            }}

    @api.onchange('product_detail_id')
    def _onchange_product_detail_id(self):
        for record in self:
            if record.product_detail_id:
                record.product_code = record.product_detail_id.\
                    product_detail_code

    @api.onchange('bidding_ids')
    def _onchange_bidding_ids(self):
        for record in self:
            record.business_contract_code = ','.join(
                record.bidding_ids.mapped('business_contract_code'))

    def action_expand_details(self):
        """(Re)build the detail lines from the sales order MTO chain.

        One detail row per manufacturing order: TYPE from the product
        board/machine kind (01 meter / 02 PCB), COUNT from the order
        quantity, SN segment bounds from the order segment fields.
        """
        Detail = self.env['sn.wsd.nqi.pt.plan.detail']
        for record in self:
            order = record.sale_order_id
            if not order:
                raise UserError(_(
                    'Pick a sales order before expanding details.'))
            line = record.sale_order_line_id
            if not line:
                lines = order.order_line._nqi_product_lines()
                if len(lines) != 1:
                    raise UserError(_(
                        'Pick a sales order line: the order has several '
                        'product lines.'))
                line = lines
                record.sale_order_line_id = line
            if not record.product_detail_id:
                record._nqi_apply_line(line)
            orders = record._nqi_manufacturing_orders()
            if not orders:
                raise UserError(_(
                    'No manufacturing order found under sales order %s '
                    '(check the MTO chain).',
                    record.sale_order_id.display_name))
            Detail.search([('plan_id', '=', record.id)]).unlink()
            Detail.create([{
                'plan_id': record.id,
                'plan_code': record.plan_code,
                'count': str(int(production.product_qty or 0)),
                'type': PRODUCT_KIND_TO_TYPE.get(
                    production.product_id._nqi_product_kind(), ''),
                'start_serial_no': production.x_sn_segment_start or '',
                'finish_serial_no': production.x_sn_segment_end or '',
            } for production in orders])
        return True

    def _nqi_manufacturing_orders(self):
        """Manufacturing orders of the sales order's MTO chain."""
        self.ensure_one()
        order = self.sale_order_id
        Production = self.env['mrp.production']
        domain = [('origin', '=', order.name)] if order.name else []
        if 'sale_line_id' in Production._fields:
            direct = [('sale_line_id.order_id', '=', order.id)]
            domain = (['|'] + domain + direct) if domain else direct
        if not domain:
            return Production
        orders = Production.search(domain)
        line = self.sale_order_line_id
        others = order.order_line.filtered('product_id') - line
        if line and others and 'sale_line_id' in Production._fields:
            # multi-line order: an order linked to another line belongs
            # to that line's plan; unlinked sub-level orders stay
            orders = orders.filtered(
                lambda production: not production.sale_line_id
                or production.sale_line_id not in others)
        return orders


class NqiPtPlanDetail(models.Model):
    _inherit = 'sn.wsd.nqi.pt.plan.detail'

    plan_id = fields.Many2one(
        'sn.wsd.nqi.pt.plan', string='NQI Plan', index=True,
        ondelete='cascade')
