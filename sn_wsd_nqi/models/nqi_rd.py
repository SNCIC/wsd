from odoo import fields, models


class NqiRdProductInfo(models.Model):
    """NQI RD_PRODUCT_INFO mirror (product information).

    First mirror model of the chapter-1 family: Char columns mirror the
    NQI columns verbatim (payload = field name upper-cased), the
    envelope mixin carries the shared columns, and ``NQI_REQUIRED``
    lists the NQI-side mandatory columns for the completeness gate.
    Anchors and onchange bring-in land with the staging batch.
    """
    _name = 'sn.wsd.nqi.rd.product.info'
    _inherit = 'sn.wsd.nqi.staging.mixin'
    _description = 'NQI Product Info (RD_PRODUCT_INFO)'
    _rec_name = 'product_code'

    NQI_REQUIRED = (
        'product_code', 'product_type', 'product_name', 'product_categid',
        'product_design_basis',
    )

    product_code = fields.Char(
        string='Product Code', index=True,
        help='Globally unique product code = test report / list number.')
    product_type = fields.Char(string='Product Type')
    product_name = fields.Char(string='Product Name')
    product_categid_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Product Category',
        domain="[('code_type', '=', 'PRODUCT_CATEGID')]",
        ondelete='restrict')
    product_categid = fields.Char(
        string='Product Category Code',
        help='CODE_ID snapshot of PRODUCT_CATEGID (P_CODE).')
    product_design_basis = fields.Char(string='Product Design Basis')
    remarks = fields.Text(string='Remarks')

    _product_code_company_uniq = models.Constraint(
        'unique(company_id, product_code)',
        'Product code must be unique per company.',
    )
