from odoo import api, fields, models

from .eip_push import C, F, K, T


class EipProcessWork(models.Model):
    """Process work report pushed to the EIP platform (single-table
    interface): what a workstation reported on a work order."""
    _name = 'sn.wsd.eip.process.work'
    _description = 'EIP Process Work Report'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    EIP_INTERFACE = 'process_work'
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        F('ipoNo', 'ipo_no', add=True, update=True),
        F('insideNo', 'inside_no'),
        F('deviceNo', 'device_no'),
        F('productBatchNo', 'product_batch_no', add=True),
        F('processName', 'process_name', add=True),
        F('categoryCode', 'category_id.code', add=True),
        F('subclassCode', 'subclass_id.code', add=True),
        F('processCode', 'process_code', add=True, update=True),
        F('processNo', 'process_no'),
        F('workshopId', 'workshop_id'),
        F('workshopCode', 'workshop_code'),
        F('workshopName', 'workshop_name'),
        F('woNo', 'wo_no', add=True, update=True),
        F('productId', 'entity_no'),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True, update=True),
        F('planStartTime', 'plan_start_time'),
        F('planEndTime', 'plan_end_time'),
        # the parameter-table key names (the samples show ...Time)
        F('actualStartDate', 'actual_start_time'),
        F('actualFinishDate', 'actual_finish_time'),
        F('orderStatus', 'order_status'),
        F('buyerProvince', 'buyer_province', add=True),
        F('wavyStatus', 'wavy_status'),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    ipo_no = fields.Char(
        string='Production Order No.', required=True, index=True)
    inside_no = fields.Char(
        string='Product Internal ID',
        help='Counted as 0 by the platform when empty.')
    device_no = fields.Char(
        string='Device No.',
        help='One or more device numbers joined with "&".')
    product_batch_no = fields.Char(string='Production Batch No.')
    process_name = fields.Char(string='Process Name')
    category_id = fields.Many2one(
        'sn.wsd.eip.category', string='Category Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_category_id'))
    subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='Subclass Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_subclass_id'))
    process_code_id = fields.Many2one(
        'sn.wsd.eip.process.code', string='Process Code',
        help='Picks the code; it is copied into the payload key and can '
             'also be typed freely.')
    process_code = fields.Char(string='Process Code', index=True)
    process_no = fields.Char(string='Process Route No.')
    workshop_id = fields.Char(string='Workshop ID')
    workshop_code = fields.Char(string='Workshop Code')
    workshop_name = fields.Char(string='Workshop Name')
    wo_no = fields.Char(string='Work Order No.', required=True, index=True)
    entity_no = fields.Char(string='Entity ID')
    plan_start_time = fields.Datetime(string='Planned Start Time')
    plan_end_time = fields.Datetime(string='Planned End Time')
    actual_start_time = fields.Datetime(string='Actual Start Time')
    actual_finish_time = fields.Datetime(string='Actual Finish Time')
    order_status = fields.Char(string='Order Status')
    buyer_province = fields.Char(
        string='Purchaser Province', help='Without the "province" suffix.')
    wavy_status = fields.Selection(
        [('0', 'None'), ('1', 'Present')], string='Wave Information')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')

    @api.onchange('process_code_id')
    def _onchange_process_code_id(self):
        if self.process_code_id:
            self.process_code = self.process_code_id.code
            if not self.process_name:
                self.process_name = self.process_code_id.name

    def _eip_document_ref(self):
        self.ensure_one()
        return '%s/%s' % (self.wo_no, self.process_code or '')
