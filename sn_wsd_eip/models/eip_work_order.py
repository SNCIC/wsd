from odoo import api, fields, models

from .eip_push import C, F, K, T


class EipWorkOrder(models.Model):
    """Work order pushed to the EIP platform (single-table interface):
    the shop-floor decomposition of a production order. Created from a
    production order or by hand."""
    _name = 'sn.wsd.eip.work.order'
    _description = 'EIP Work Order'
    _rec_name = 'wo_no'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'wo_no desc, id desc'
    _check_company_auto = True

    EIP_INTERFACE = 'work_order'
    EIP_SEQUENCE = 'sn.wsd.eip.work.order'
    EIP_NUMBER_FIELD = 'wo_no'
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        F('ipoNo', 'ipo_no', add=True, update=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        C('supplierName', 'supplier_name', add=True, update=True),
        F('woNo', 'wo_no', add=True, update=True),
        F('categoryCode', 'category_id.code', add=True),
        F('subclassCode', 'subclass_id.code', add=True),
        F('materialsCode', 'materials_code', add=True),
        F('materialsDescription', 'materials_description'),
        F('materialsBatch', 'materials_batch'),
        F('amount', 'amount', add=True),
        F('unit', 'unit', add=True),
        F('planStartDate', 'plan_start_date', add=True),
        F('planFinishDate', 'plan_finish_date', add=True),
        F('actualStartDate', 'actual_start_date'),
        F('actualFinishDate', 'actual_finish_date'),
        F('woStatus', 'wo_status', add=True),
        F('entityCode', 'entity_code'),
        F('processRouteNo', 'process_route_no'),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True, update=True),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
        F('modelSpec', 'model_spec'),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    production_order_id = fields.Many2one(
        'sn.wsd.eip.production.order', string='Production Order',
        ondelete='set null', check_company=True, index=True,
        help='Picks the production order; its number is copied into '
             'the payload key.')
    ipo_no = fields.Char(
        string='Production Order No.', required=True, index=True,
        help='Number of the production order this work order belongs to.')
    wo_no = fields.Char(
        string='Work Order No.', required=True, index=True,
        copy=False, default=lambda self: self._eip_new_number())
    category_id = fields.Many2one(
        'sn.wsd.eip.category', string='Category Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_category_id'))
    subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='Subclass Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_subclass_id'))
    materials_code = fields.Char(string='Material Code')
    materials_description = fields.Char(string='Material Description')
    materials_batch = fields.Char(string='Material Batch')
    amount = fields.Char(string='Quantity')
    unit = fields.Char(string='Unit of Measure')
    plan_start_date = fields.Date(string='Planned Start')
    plan_finish_date = fields.Date(string='Planned Finish')
    actual_start_date = fields.Date(string='Actual Start')
    actual_finish_date = fields.Date(string='Actual Finish')
    wo_status = fields.Selection(
        [('1', 'Created'), ('2', 'Incoming Inspection'),
         ('3', 'In Production'), ('4', 'Factory Test'),
         ('5', 'Packed and Stocked')],
        string='Status', default='1')
    entity_code = fields.Char(
        string='Entity ID',
        help='One entity ID, or a range like 0001-0100 kept continuous.')
    process_route_no = fields.Char(string='Process Route No.')
    model_spec = fields.Char(string='Model Specification')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')

    _wo_uniq = models.Constraint(
        'unique(company_id, wo_no)',
        'The work order number must be unique per company.',
    )

    @api.onchange('production_order_id')
    def _onchange_production_order_id(self):
        order = self.production_order_id
        if order:
            self.ipo_no = order.ipo_no
            self.category_id = order.category_id
            self.subclass_id = order.subclass_id
            self.materials_code = order.materials_code
            self.materials_description = (order.materials_desc
                or order.purchase_line_id.material_desc or '')
            self.amount = order.amount
            self.unit = order.unit

    def _eip_document_ref(self):
        self.ensure_one()
        return self.wo_no
