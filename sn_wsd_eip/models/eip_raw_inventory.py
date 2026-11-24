from odoo import fields, models

from .eip_push import C, F, K, N, T

RAW_LINE_SPEC = (
    F('batchCode', 'batch_code', add=True, update=True),
    F('productAmount', 'product_amount', add=True),
    T('dataSourceCreatetime', add=True, update=True),
    F('remark', 'remark'),
)


class EipRawInventory(models.Model):
    """Key raw material inventory pushed to the EIP platform, with the
    incoming batches below it."""
    _name = 'sn.wsd.eip.raw.inventory'
    _description = 'EIP Raw Material Inventory'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'mat_code, id'
    _check_company_auto = True

    EIP_INTERFACE = 'raw_inventory'
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        C('supplierName', 'supplier_name', add=True, update=True),
        F('matName', 'mat_name', add=True),
        F('matCode', 'mat_code', add=True, update=True),
        F('matNum', 'mat_num', add=True),
        F('matUnit', 'mat_unit', add=True),
        F('matDescription', 'mat_description'),
        F('matProdAddr', 'mat_prod_addr'),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True, update=True),
        F('remark', 'remark'),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
        N('data', 'line_ids', RAW_LINE_SPEC),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    mat_name = fields.Char(string='Raw Material Name')
    mat_code = fields.Char(
        string='Raw Material Code', required=True, index=True,
        help='From the list the EIP platform provides.')
    mat_num = fields.Char(string='Inventory Quantity')
    mat_unit = fields.Char(string='Raw Material Unit')
    mat_description = fields.Char(string='Raw Material Description')
    mat_prod_addr = fields.Char(string='Raw Material Origin')
    remark = fields.Char(string='Remark')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')
    line_ids = fields.One2many(
        'sn.wsd.eip.raw.inventory.line', 'inventory_id',
        string='Incoming Batches')

    _mat_uniq = models.Constraint(
        'unique(company_id, mat_code)',
        'The raw material code must be unique per company.',
    )

    def _eip_document_ref(self):
        self.ensure_one()
        return self.mat_code


class EipRawInventoryLine(models.Model):
    """One incoming batch of a raw material."""
    _name = 'sn.wsd.eip.raw.inventory.line'
    _description = 'EIP Raw Material Inventory Line'
    _inherit = 'sn.wsd.eip.push.line.mixin'
    _order = 'batch_code, id'
    _check_company_auto = True

    EIP_LINES = RAW_LINE_SPEC
    EIP_PARENT_FIELD = 'inventory_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    inventory_id = fields.Many2one(
        'sn.wsd.eip.raw.inventory', string='Raw Material', required=True,
        index=True, ondelete='cascade', check_company=True)
    batch_code = fields.Char(string='Incoming Batch No.')
    product_amount = fields.Char(string='Batch Remaining Quantity')
    remark = fields.Char(string='Remark')
