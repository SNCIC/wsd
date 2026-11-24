from odoo import api, fields, models

from .eip_push import C, F, K, N, T

SPARE_LINE_SPEC = (
    F('productLot', 'product_lot', add=True, update=True),
    F('productAmount', 'product_amount', add=True),
    T('dataSourceCreatetime', add=True, update=True),
    F('remark', 'remark', add=True),
)

FINISHED_LINE_SPEC = (
    F('poNo', 'po_no'),
    F('batchCode', 'batch_code', add=True, update=True),
    F('productAmount', 'product_amount', add=True),
    F('purchaseName', 'purchase_name'),
    F('dataSource', 'data_source', add=True, update=True),
    T('dataSourceCreatetime', add=True, update=True),
    F('remark', 'remark'),
)


class EipSpareInventory(models.Model):
    """Spare parts inventory pushed to the EIP platform; the spec asks
    for a refresh every 24 hours."""
    _name = 'sn.wsd.eip.spare.inventory'
    _description = 'EIP Spare Parts Inventory'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'spare_product_code, id'
    _check_company_auto = True

    EIP_INTERFACE = 'spare_inventory'
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        C('supplierName', 'supplier_name', add=True),
        F('spareProductCode', 'spare_product_code', add=True, update=True),
        F('productDec', 'product_dec', add=True),
        F('productAmount', 'product_amount', add=True),
        F('productUnit', 'product_unit', add=True),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True, update=True),
        F('remark', 'remark'),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
        N('itemList', 'line_ids', SPARE_LINE_SPEC),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    spare_product_code = fields.Char(
        string='Spare Part No.', required=True, index=True,
        help='Issued by the EIP platform; typed by hand.')
    product_dec = fields.Char(string='Spare Part Description')
    product_amount = fields.Char(string='Remaining Quantity')
    product_unit = fields.Char(string='Unit of Measure')
    remark = fields.Char(string='Remark')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')
    line_ids = fields.One2many(
        'sn.wsd.eip.spare.inventory.line', 'inventory_id',
        string='Batches')

    _spare_uniq = models.Constraint(
        'unique(company_id, spare_product_code)',
        'The spare part number must be unique per company.',
    )

    def _eip_document_ref(self):
        self.ensure_one()
        return self.spare_product_code


class EipSpareInventoryLine(models.Model):
    """One batch of a spare part."""
    _name = 'sn.wsd.eip.spare.inventory.line'
    _description = 'EIP Spare Parts Inventory Line'
    _inherit = 'sn.wsd.eip.push.line.mixin'
    _order = 'product_lot, id'
    _check_company_auto = True

    EIP_LINES = SPARE_LINE_SPEC
    EIP_PARENT_FIELD = 'inventory_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    inventory_id = fields.Many2one(
        'sn.wsd.eip.spare.inventory', string='Spare Part', required=True,
        index=True, ondelete='cascade', check_company=True)
    product_lot = fields.Char(string='Batch No.')
    product_amount = fields.Char(string='Remaining Quantity')
    remark = fields.Char(string='Remark')


class EipFinishedInventory(models.Model):
    """Finished goods inventory pushed to the EIP platform; the spec
    asks for one push per product (and per batch) every day."""
    _name = 'sn.wsd.eip.finished.inventory'
    _description = 'EIP Finished Goods Inventory'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'product_code, id'
    _check_company_auto = True

    EIP_INTERFACE = 'finished_inventory'
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True, update=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        C('supplierName', 'supplier_name', add=True, update=True),
        F('productCode', 'product_code', add=True, update=True),
        F('productName', 'product_name', add=True),
        F('productAmount', 'product_amount', add=True),
        F('productUnit', 'product_unit', add=True),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True, update=True),
        F('remark', 'remark'),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
        N('itemList', 'line_ids', FINISHED_LINE_SPEC),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='Subclass Code',
        help='Picks the code and the name; the platform treats the '
             'subclass as the product code.')
    product_code = fields.Char(
        string='Product Code', required=True, index=True,
        help='The material subclass code of the platform.')
    product_name = fields.Char(string='Product Name')
    product_amount = fields.Char(string='Remaining Quantity')
    product_unit = fields.Char(string='Unit of Measure')
    remark = fields.Char(string='Remark')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')
    line_ids = fields.One2many(
        'sn.wsd.eip.finished.inventory.line', 'inventory_id',
        string='Batches')

    _product_uniq = models.Constraint(
        'unique(company_id, product_code)',
        'The product code must be unique per company.',
    )

    @api.onchange('subclass_id')
    def _onchange_subclass_id(self):
        if self.subclass_id:
            self.product_code = self.subclass_id.code
            self.product_name = self.subclass_id.name

    def _eip_document_ref(self):
        self.ensure_one()
        return self.product_code


class EipFinishedInventoryLine(models.Model):
    """One batch of a finished product."""
    _name = 'sn.wsd.eip.finished.inventory.line'
    _description = 'EIP Finished Goods Inventory Line'
    _inherit = 'sn.wsd.eip.push.line.mixin'
    _order = 'batch_code, id'
    _check_company_auto = True

    EIP_LINES = FINISHED_LINE_SPEC
    EIP_PARENT_FIELD = 'inventory_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    inventory_id = fields.Many2one(
        'sn.wsd.eip.finished.inventory', string='Finished Product',
        required=True, index=True, ondelete='cascade', check_company=True)
    po_no = fields.Char(string='Grid Purchase Order No.')
    batch_code = fields.Char(string='Incoming Batch No.')
    product_amount = fields.Char(string='Batch Remaining Quantity')
    purchase_name = fields.Char(string='Purchaser Name')
    data_source = fields.Selection(
        [('0', 'Supplier'), ('1', 'Gateway'), ('2', 'Proxy')],
        string='Data Source')
    remark = fields.Char(string='Remark')
