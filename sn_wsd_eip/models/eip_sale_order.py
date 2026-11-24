from odoo import fields, models

from .eip_push import C, F, K, N, T

# Field list of one sale order line (the category / subclass codes
# live on the line per the interface samples)
SALE_LINE_SPEC = (
    F('soItemNo', 'so_item_no', add=True, update=True),
    F('categoryCode', 'category_id.code', add=True),
    F('subclassCode', 'subclass_id.code', add=True),
    F('poItemId', 'po_item_id', add=True, update=True),
    F('productCode', 'product_code', add=True),
    F('productName', 'product_name', add=True),
    F('productUnit', 'product_unit', add=True),
    F('productAmount', 'product_amount', add=True),
    F('ownerId', 'owner_code'),
    F('openId', 'open_code'),
)


class EipSaleOrder(models.Model):
    """Sales order pushed to the EIP platform: the supplier-side sales
    document linked to the grid purchase order lines via its lines."""
    _name = 'sn.wsd.eip.sale.order'
    _description = 'EIP Sale Order'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'so_no desc, id desc'
    _check_company_auto = True

    EIP_INTERFACE = 'sale_order'
    EIP_SEQUENCE = 'sn.wsd.eip.sale.order'
    EIP_NUMBER_FIELD = 'so_no'
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        F('soNo', 'so_no', add=True, update=True),
        F('buyerCode', 'buyer_code'),
        F('buyerName', 'buyer_name', add=True),
        F('buyerProvince', 'buyer_province'),
        F('soStatus', 'so_status'),
        N('itemList', 'line_ids', SALE_LINE_SPEC),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    so_no = fields.Char(
        string='Sale Order No.', required=True, index=True,
        copy=False, default=lambda self: self._eip_new_number())
    buyer_code = fields.Char(string='Purchaser Code')
    buyer_name = fields.Char(string='Purchaser Name')
    buyer_province = fields.Char(
        string='Purchaser Province', help='Without the "province" suffix.')
    so_status = fields.Char(string='Sale Order Status')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')
    line_ids = fields.One2many(
        'sn.wsd.eip.sale.order.line', 'sale_order_id', string='Lines')

    _so_uniq = models.Constraint(
        'unique(company_id, so_no)',
        'The sale order number must be unique per company.',
    )

    def _eip_document_ref(self):
        self.ensure_one()
        return self.so_no


class EipSaleOrderLine(models.Model):
    """One sale order line; the category / subclass codes live on the
    line per the interface samples."""
    _name = 'sn.wsd.eip.sale.order.line'
    _description = 'EIP Sale Order Line'
    _inherit = 'sn.wsd.eip.push.line.mixin'
    _order = 'so_item_no, id'
    _check_company_auto = True

    EIP_LINES = SALE_LINE_SPEC
    EIP_PARENT_FIELD = 'sale_order_id'
    EIP_LINE_NO_FIELD = 'so_item_no'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    sale_order_id = fields.Many2one(
        'sn.wsd.eip.sale.order', string='Sale Order', required=True,
        index=True, ondelete='cascade', check_company=True)
    so_item_no = fields.Char(string='Line No.')
    category_id = fields.Many2one(
        'sn.wsd.eip.category', string='Category Code', index=True)
    subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='Subclass Code', index=True)
    po_item_id = fields.Char(
        string='Grid Purchase Order Line ID', index=True,
        help='Several IDs are joined with "&".')
    product_code = fields.Char(string='Material Code')
    product_name = fields.Char(string='Material Name')
    product_unit = fields.Char(string='Material Unit')
    product_amount = fields.Char(string='Material Quantity')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')
