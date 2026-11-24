from odoo import api, fields, models

# Response keys of the purchase-order interface -> line field (the
# response parameter table of the spec). Every key the platform returns
# is kept on the line: a line is the faithful mirror of one returned row.
PULL_LINE_FIELDS = {
    'poNo': 'po_no',
    'poItemNo': 'po_item_no',
    'poItemId': 'po_item_id',
    'conCode': 'con_code',
    'conName': 'con_name',
    'buyerName': 'buyer_name',
    'buyerCode': 'buyer_code',
    'materialCode': 'material_code',
    'materialDesc': 'material_desc',
    'amount': 'amount',
    'sellerConCode': 'seller_con_code',
    'serialNumber': 'serial_number',
    'sellerSignTime': 'seller_sign_time',
    'conType': 'con_type',
    'prjCode': 'prj_code',
    'prjName': 'prj_name',
    'matCode': 'mat_code',
    'fixedTechId': 'fixed_tech_id',
    'pkgNo': 'pkg_no',
    'bidBatCode': 'bid_bat_code',
    'extDes': 'ext_des',
    'matMaxCode': 'mat_max_code',
    'matMedCode': 'mat_med_code',
    'matMinCode': 'mat_min_code',
    'matMaxName': 'mat_max_name',
    'matMedName': 'mat_med_name',
    'matMinName': 'mat_min_name',
    'modifyTime': 'modify_time',
}
PULL_DATE_FIELDS = frozenset({'seller_sign_time'})
PULL_DATETIME_FIELDS = frozenset({'modify_time'})
# Contract-level fields mirrored on the order header: they take the
# value of the order's latest returned row.
ORDER_HEADER_FIELDS = (
    'po_no', 'con_code', 'con_name', 'seller_con_code', 'buyer_name',
    'buyer_code', 'seller_sign_time', 'con_type', 'bid_bat_code',
    'modify_time',
)


def _eip_text(value):
    """Mirror a JSON scalar as stored text: keep its literal text
    (18-digit line IDs, decimal amounts), drop blanks."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value.strip() or False
    return str(value)


class EipPurchaseOrder(models.Model):
    """Header of a grid purchase order, as pulled from the EIP platform:
    one record per purchase order number, contract-level fields only."""
    _name = 'sn.wsd.eip.purchase.order'
    _description = 'EIP Grid Purchase Order'
    _order = 'po_no desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    po_no = fields.Char(
        string='Purchase Order No.', required=True, index=True,
        help='Purchase order number issued by ECP.')
    con_code = fields.Char(string='Contract No.')
    con_name = fields.Char(string='Contract Name')
    seller_con_code = fields.Char(
        string='Contract No. (Legal System)',
        help='Contract number of the State Grid legal system.')
    buyer_code = fields.Char(string='Purchaser Code')
    buyer_name = fields.Char(string='Purchaser Name')
    seller_sign_time = fields.Date(string='Contract Signing Date')
    con_type = fields.Char(
        string='Contract Type',
        help='1 standard contract, 2 framework stock, '
             '3 purchase supply note.')
    bid_bat_code = fields.Char(string='Bidding Batch No.')
    modify_time = fields.Datetime(string='Last Updated (Platform)')
    line_count = fields.Integer(
        string='Line Count', compute='_compute_line_count')
    line_ids = fields.One2many(
        'sn.wsd.eip.purchase.order.line', 'order_id',
        string='Purchase Order Lines')

    _po_uniq = models.Constraint(
        'unique(company_id, po_no)',
        'The purchase order number must be unique per company.',
    )

    @api.depends('line_ids')
    def _compute_line_count(self):
        for order in self:
            order.line_count = len(order.line_ids)


class EipPurchaseOrderLine(models.Model):
    """One line item of a grid purchase order: the exact mirror of one
    returned row. ``po_item_id`` is the ID EIP generates for the line
    and the only link the downstream interfaces accept, so it is stored
    as text and never converted to a number."""
    _name = 'sn.wsd.eip.purchase.order.line'
    _description = 'EIP Grid Purchase Order Line'
    _order = 'po_no, po_item_no, id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    order_id = fields.Many2one(
        'sn.wsd.eip.purchase.order', string='Purchase Order',
        required=True, index=True, ondelete='cascade', check_company=True)
    po_no = fields.Char(string='Purchase Order No.', required=True, index=True)
    po_item_no = fields.Char(string='Line No.')
    po_item_id = fields.Char(
        string='Purchase Order Line ID', required=True, index=True,
        help='ID EIP generated for this line item; the only key the '
             'other interfaces use to link to it.')
    con_code = fields.Char(string='Contract No.')
    con_name = fields.Char(string='Contract Name')
    buyer_name = fields.Char(string='Purchaser Name')
    buyer_code = fields.Char(string='Purchaser Code')
    material_code = fields.Char(string='Purchaser Material Code')
    material_desc = fields.Char(string='Purchaser Material Description')
    amount = fields.Char(string='Ordered Quantity')
    seller_con_code = fields.Char(string='Contract No. (Legal System)')
    serial_number = fields.Char(string='Technical Spec Serial No.')
    seller_sign_time = fields.Date(string='Contract Signing Date')
    con_type = fields.Char(string='Contract Type')
    prj_code = fields.Char(string='Project No.')
    prj_name = fields.Char(string='Project Name')
    mat_code = fields.Char(string='Grid Material Code')
    fixed_tech_id = fields.Char(string='Fixed Technical ID')
    pkg_no = fields.Char(string='Contract Package No.')
    bid_bat_code = fields.Char(string='Bidding Batch No.')
    ext_des = fields.Text(string='Fixed ID Description')
    mat_max_code = fields.Char(string='Material Class Code')
    mat_med_code = fields.Char(string='Material Family Code')
    mat_min_code = fields.Char(string='Material Type Code')
    mat_max_name = fields.Char(string='Material Class')
    mat_med_name = fields.Char(string='Material Family')
    mat_min_name = fields.Char(string='Material Type')
    modify_time = fields.Datetime(string='Last Updated (Platform)')

    _item_uniq = models.Constraint(
        'unique(company_id, po_item_id)',
        'The purchase order line ID must be unique per company.',
    )

    @api.model
    def _eip_pull_row_values(self, row, company):
        """Field values of one returned row."""
        transport = self.env['sn.wsd.eip.transport']
        values = {}
        for key, field_name in PULL_LINE_FIELDS.items():
            value = row.get(key)
            if field_name in PULL_DATE_FIELDS:
                value = transport._eip_parse_date(value)
            elif field_name in PULL_DATETIME_FIELDS:
                value = transport._eip_parse_datetime(value)
            else:
                value = _eip_text(value)
            values[field_name] = value
        values['company_id'] = company.id
        return values

    @api.model
    def _eip_pull_upsert(self, rows, company):
        """Mirror one returned page: one line per line ID, one order per
        purchase order number. Returns the number of lines stored."""
        Order = self.env['sn.wsd.eip.purchase.order']
        values_list = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            values = self._eip_pull_row_values(row, company)
            # without these two a row can be neither linked nor upserted
            if values['po_item_id'] and values['po_no']:
                values_list.append(values)
        if not values_list:
            return 0

        item_ids = [values['po_item_id'] for values in values_list]
        existing = self.search([
            ('company_id', '=', company.id),
            ('po_item_id', 'in', item_ids),
        ])
        lines_by_item = {line.po_item_id: line for line in existing}
        orders = Order.search([
            ('company_id', '=', company.id),
            ('po_no', 'in', list({v['po_no'] for v in values_list})),
        ])
        orders_by_no = {order.po_no: order for order in orders}

        new_lines = []
        headers = {}
        for values in values_list:
            header = {field: values[field] for field in ORDER_HEADER_FIELDS}
            order = orders_by_no.get(values['po_no'])
            if order is None:
                order = Order.create(dict(header, company_id=company.id))
                orders_by_no[values['po_no']] = order
            else:
                # written once per order below; the latest row wins
                headers[order] = header
            line_values = {
                field: value for field, value in values.items()
                if field != 'company_id'}
            line = lines_by_item.get(values['po_item_id'])
            if line is None:
                new_lines.append(dict(line_values, order_id=order.id))
            else:
                line.write(line_values)
        for order, header in headers.items():
            order.write(header)
        if new_lines:
            self.create(new_lines)
        return len(values_list)
