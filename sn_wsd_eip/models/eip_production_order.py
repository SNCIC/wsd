from odoo import _, api, fields, models

from .eip_push import C, F, K, T


class EipProductionOrder(models.Model):
    """Production order pushed to the EIP platform (single-table
    interface). Created from a grid purchase order line or by hand."""
    _name = 'sn.wsd.eip.production.order'
    _description = 'EIP Production Order'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'ipo_no desc, id desc'
    _check_company_auto = True

    EIP_INTERFACE = 'production_order'
    EIP_SEQUENCE = 'sn.wsd.eip.production.order'
    EIP_NUMBER_FIELD = 'ipo_no'
    # Parameter table of the spec, ADD / UPDATE required flags included
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        F('ipoType', 'ipo_type', add=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        C('supplierName', 'supplier_name', add=True, update=True),
        F('ipoNo', 'ipo_no', add=True, update=True),
        F('categoryCode', 'category_id.code', add=True),
        F('subclassCode', 'subclass_id.code', add=True),
        F('scheduleCode', 'schedule_code'),
        F('poItemId', 'po_item_id', add=True, update=True),
        F('dataType', 'data_type', update=True),
        F('soItemNo', 'so_item_no'),
        F('materialsCode', 'materials_code', add=True),
        F('materialsName', 'materials_name', add=True),
        F('materialsUnit', 'materials_unit', add=True),
        F('materialsDesc', 'materials_desc', add=True),
        F('amount', 'amount', add=True),
        F('unit', 'unit', add=True),
        F('productIdGrpNo', 'product_id_grp_no'),
        F('productIdType', 'product_id_type'),
        F('productModel', 'product_model'),
        F('planStartDate', 'plan_start_date', add=True),
        F('planFinishDate', 'plan_finish_date', add=True),
        F('actualStartDate', 'actual_start_date'),
        F('actualFinishDate', 'actual_finish_date'),
        F('plantName', 'plant_name'),
        F('workshopName', 'workshop_name'),
        F('ipoStatus', 'ipo_status'),
        F('center', 'center'),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True, update=True),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    ipo_type = fields.Selection(
        [('0', 'Default'), ('1', 'Secondary Panel Cabinet'),
         ('2', 'Secondary Device')],
        string='Order Type', default='0',
        help='0 is the default value and can be ignored.')
    ipo_no = fields.Char(
        string='Production Order No.', required=True, index=True,
        copy=False, default=lambda self: self._eip_new_number())
    category_id = fields.Many2one(
        'sn.wsd.eip.category', string='Category Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_category_id'))
    subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='Subclass Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_subclass_id'))
    schedule_code = fields.Char(
        string='Schedule Code',
        help='Key of the production schedule this order belongs to.')
    po_item_id = fields.Char(
        string='Grid Purchase Order Line ID', index=True,
        help='ID EIP generated for the purchase order line (or the '
             'supply note line) this order is produced for.')
    purchase_line_id = fields.Many2one(
        'sn.wsd.eip.purchase.order.line', string='Grid Purchase Order Line',
        ondelete='set null', check_company=True, index=True,
        help='Picks the line; its ID is copied into the payload key.')
    data_type = fields.Selection(
        [('1', 'Grid Purchase Order Line'), ('2', 'Sales Order Line')],
        string='Link Type', default='1',
        help='1: the line ID field holds a grid purchase order line ID; '
             '2: it holds the sales order number.')
    so_item_no = fields.Char(
        string='Sales Order Line No.',
        help='Required when the link type is the sales order line.')
    materials_code = fields.Char(string='Material Code')
    materials_name = fields.Char(string='Material Name')
    materials_unit = fields.Char(string='Material Unit')
    materials_desc = fields.Char(string='Material Description')
    amount = fields.Char(string='Quantity')
    unit = fields.Char(string='Unit of Measure')
    product_id_grp_no = fields.Char(string='Product ID Group')
    product_id_type = fields.Char(string='Product ID Type')
    product_model = fields.Char(string='Product Model')
    plan_start_date = fields.Date(string='Planned Start')
    plan_finish_date = fields.Date(string='Planned Finish')
    actual_start_date = fields.Date(string='Actual Start')
    actual_finish_date = fields.Date(string='Actual Finish')
    plant_name = fields.Char(string='Plant')
    workshop_name = fields.Char(string='Workshop')
    ipo_status = fields.Selection(
        [('1', 'Created'), ('2', 'Incoming Inspection'),
         ('3', 'In Production'), ('4', 'Factory Test'),
         ('5', 'Packed and Stocked')],
        string='Status')
    center = fields.Char(string='Production Center')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')

    _ipo_uniq = models.Constraint(
        'unique(company_id, ipo_no)',
        'The production order number must be unique per company.',
    )

    @api.onchange('purchase_line_id')
    def _onchange_purchase_line_id(self):
        if self.purchase_line_id:
            self.po_item_id = self.purchase_line_id.po_item_id

    def _eip_document_ref(self):
        self.ensure_one()
        return self.ipo_no

    # ------------------------------------------------------------------
    # derive: work order(s) of this production order
    # ------------------------------------------------------------------

    def action_create_work_order(self):
        """Create a draft work order of this production order; only
        required fields are brought over (user decision 2026-11-24)."""
        self.ensure_one()
        work_order = self.env['sn.wsd.eip.work.order'].create({
            'company_id': self.company_id.id,
            'production_order_id': self.id,
            'ipo_no': self.ipo_no,
            'category_id': self.category_id.id,
            'subclass_id': self.subclass_id.id,
            'materials_code': self.materials_code,
            'amount': self.amount,
            'unit': self.unit,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Work Order'),
            'res_model': 'sn.wsd.eip.work.order',
            'view_mode': 'form',
            'res_id': work_order.id,
        }
