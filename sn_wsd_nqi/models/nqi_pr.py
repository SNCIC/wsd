"""Generated from the NQI data model V2.1 docx (see
build_tmp/nqi_explore/gen_models.py and fields.json)."""
from odoo import api, fields, models

class NqiBiddingInfo(models.Model):
    """NQI PR_BIDDING_INFO mirror."""
    _name = 'sn.wsd.nqi.pr.bidding.info'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Bidding Info'
    _rec_name = 'business_contract_code'

    NQI_REQUIRED = (
        'business_contract_code',
        'bidding_batch',
        'bidding_party_a',
        'bidding_time',
        'bidding_count',
        'uaser_nature',
        'development_project_no',
        'software_version',
        'hardware_version',
        'product_detail_code',
    )

    business_contract_code = fields.Char(index=True)
    bidding_batch = fields.Char()
    bidding_position = fields.Char()
    bidding_party_a_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Bidding Party A',
        domain="[('code_type', '=', 'BIDDING_PARTY_A')]",
        ondelete='restrict')
    bidding_party_a = fields.Char()
    bidding_time = fields.Char()
    bidding_count = fields.Char()
    uaser_nature = fields.Char()
    development_project_no = fields.Char()
    software_version = fields.Char()
    hardware_version = fields.Char()
    product_detail_code = fields.Char()
    internal_control_code = fields.Char()

    @api.onchange('bidding_party_a_id')
    def _onchange_bidding_party_a_id(self):
        for record in self:
            record.bidding_party_a = (record.bidding_party_a_id.code_id
                or '')

class NqiBiddingChange(models.Model):
    """NQI PR_BIDDING_CHANGE_RECOND mirror."""
    _name = 'sn.wsd.nqi.pr.bidding.change'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Bidding Change'
    _rec_name = 'change_record_code'

    NQI_REQUIRED = (
        'change_record_code',
        'change_type',
        'change_content',
        'change_result',
        'change_time',
        'business_contract_code',
        'product_detail_code',
        'new_product_code',
        'new_product_hard_code',
        'new_product_soft_code',
    )

    change_record_code = fields.Char(index=True)
    change_type = fields.Char()
    change_content = fields.Text()
    change_result = fields.Char()
    change_time = fields.Char()
    business_contract_code = fields.Char(index=True)
    product_detail_code = fields.Char()
    new_product_code = fields.Char()
    new_module_type = fields.Char()
    new_product_hard_code = fields.Char()
    new_product_soft_code = fields.Char()
    file_url = fields.Char()
    status = fields.Char()

class NqiPurchasePlan(models.Model):
    """NQI PR_COMPONENT_PURCHASE_PLAN mirror."""
    _name = 'sn.wsd.nqi.pr.purchase.plan'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Purchase Plan'
    _rec_name = 'plan_code'

    NQI_REQUIRED = (
        'purchase_code',
        'component_code',
        'supplier_enterprise_code',
        'purchase_num',
        'arrived_time',
    )

    purchase_id = fields.Many2one(
        'purchase.order', string='Purchase Order',
        ondelete='set null', index=True, tracking=True)
    purchase_code = fields.Char()
    bidding_batch = fields.Char()
    business_contract_code = fields.Char(index=True)
    plan_code = fields.Char(index=True)
    component_code = fields.Char()
    supplier_enterprise_code = fields.Char()
    purchase_num = fields.Char()
    arrived_time = fields.Char()

class NqiArriveBatch(models.Model):
    """NQI PR_COMPONENT_ARRIVE_BATCH mirror."""
    _name = 'sn.wsd.nqi.pr.arrive.batch'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Arrive Batch'
    _rec_name = 'arrived_batch_no'

    NQI_REQUIRED = (
        'arrived_batch_no',
        'purchase_code',
        'component_code',
        'component_num',
        'arrived_date',
    )

    picking_id = fields.Many2one(
        'stock.picking', string='Receipt',
        ondelete='set null', index=True, tracking=True)
    arrived_batch_no = fields.Char()
    purchase_code = fields.Char()
    component_code = fields.Char()
    component_num = fields.Char()
    arrived_date = fields.Char()

class NqiTestResult(models.Model):
    """NQI PR_COMPONENT_TEST_RESULT mirror."""
    _name = 'sn.wsd.nqi.pr.test.result'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Test Result'
    _rec_name = 'test_record_code'

    NQI_REQUIRED = (
        'test_record_code',
        'component_code',
        'arrived_batch_no',
        'operator_code',
        'test_type',
        'test_count',
        'test_result',
        'test_date',
    )

    picking_id = fields.Many2one(
        'stock.picking', string='Receipt',
        ondelete='set null', index=True, tracking=True)
    test_record_code = fields.Char()
    component_code = fields.Char()
    arrived_batch_no = fields.Char()
    make_batch_no = fields.Char()
    device_code = fields.Char()
    operator_code = fields.Char()
    test_type = fields.Char()
    test_count = fields.Char()
    test_result = fields.Char()
    file_url = fields.Char()
    test_date = fields.Char()

class NqiUnqualified(models.Model):
    """NQI PR_UNQUALIFIED_CONTROL mirror."""
    _name = 'sn.wsd.nqi.pr.unqualified'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Unqualified'
    _rec_name = 'in_control_code'

    NQI_REQUIRED = (
        'in_control_code',
        'component_code',
        'arrived_batch_no',
        'make_batch_no',
        'cause',
        'unpass_analysis',
        'solution',
        'valid_result',
        'create_time',
        'valid_time',
    )

    product_id = fields.Many2one(
        'product.product', string='Product',
        ondelete='set null', index=True, tracking=True)
    in_control_code = fields.Char()
    component_code = fields.Char()
    arrived_batch_no = fields.Char()
    make_batch_no = fields.Char()
    cause = fields.Char()
    unpass_analysis = fields.Char()
    solution = fields.Char()
    valid_result = fields.Char()
    create_time = fields.Char()
    valid_time = fields.Char()
