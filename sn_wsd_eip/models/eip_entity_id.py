from odoo import fields, models

from .eip_push import C, F, K, T


class EipEntityId(models.Model):
    """Entity ID pushed to the EIP platform (single-table interface):
    the State Grid asset identity of one physical unit, or of a whole
    continuous range."""
    _name = 'sn.wsd.eip.entity.id'
    _description = 'EIP Entity ID'
    _rec_name = 'entity_code'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'entity_code, id'
    _check_company_auto = True

    EIP_INTERFACE = 'entity'
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        C('supplierName', 'supplier_name', add=True, update=True),
        F('entityCode', 'entity_code', add=True, update=True),
        F('poItemId', 'po_item_id', add=True, update=True),
        F('entityStatus', 'entity_status', add=True),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True, update=True),
        F('remark', 'remark'),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    entity_code = fields.Char(
        string='Entity ID', required=True, index=True,
        help='One number, or a range like 0001-0100 kept continuous.')
    po_item_id = fields.Char(
        string='Grid Purchase Order Line ID', required=True, index=True)
    entity_status = fields.Selection(
        [('0', 'Not Produced'), ('1', 'In Production'),
         ('2', 'Production Finished')],
        string='Entity Status')
    remark = fields.Char(string='Remark')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')

    _entity_uniq = models.Constraint(
        'unique(company_id, entity_code)',
        'The entity ID must be unique per company.',
    )

    def _eip_document_ref(self):
        self.ensure_one()
        return self.entity_code
