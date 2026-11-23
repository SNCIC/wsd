"""Generated from the NQI data model V2.1 docx (see
build_tmp/nqi_explore/gen_models.py and fields.json)."""
from odoo import api, fields, models

class NqiDevice(models.Model):
    """NQI ET_DEVICE_INFO mirror."""
    _name = 'sn.wsd.nqi.et.device'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Device'
    _rec_name = 'device_code'

    NQI_REQUIRED = (
        'device_code',
        'device_name',
        'device_type',
        'type',
        'property_right_type',
        'device_status',
        'test_date',
        'test_valid_date',
        'used_years',
        'buy_date',
        'device_maker',
    )

    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment Ledger',
        ondelete='set null', index=True, tracking=True)
    device_code = fields.Char()
    device_make_code = fields.Char()
    device_name = fields.Char()
    device_type = fields.Char()
    type_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Type',
        domain="[('code_type', '=', 'DEVICE_TYPE')]",
        ondelete='restrict')
    type = fields.Char()
    property_right_type = fields.Char()
    file_url = fields.Char()
    device_status = fields.Char()
    test_date = fields.Char()
    test_valid_date = fields.Char()
    used_years = fields.Char()
    buy_date = fields.Char()
    device_maker = fields.Char()
    test_num = fields.Char()

    @api.onchange('type_id')
    def _onchange_type_id(self):
        for record in self:
            record.type = (record.type_id.code_id
                or '')

class NqiPerson(models.Model):
    """NQI ET_PERSON_INFO mirror."""
    _name = 'sn.wsd.nqi.et.person'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Person'
    _rec_name = 'person_code'

    NQI_REQUIRED = (
        'person_code',
        'post_type',
    )

    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        ondelete='set null', index=True, tracking=True)
    person_code = fields.Char()
    post_type = fields.Char()

class NqiStaff(models.Model):
    """NQI ET_STAFF_INFO mirror."""
    _name = 'sn.wsd.nqi.et.staff'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Staff'

    NQI_REQUIRED = (
        'designer_num',
        'metrologist_num',
        'testing_personnel_num',
    )

    total_num = fields.Char()
    manager_num = fields.Char()
    senior_manager_num = fields.Char()
    middle_manager_num = fields.Char()
    designer_num = fields.Char()
    senior_designer_num = fields.Char()
    middle_designer_num = fields.Char()
    mechanic_num = fields.Char()
    senior_skilled_worker_num = fields.Char()
    middle_skilled_worker_num = fields.Char()
    metrologist_num = fields.Char()
    testing_personnel_num = fields.Char()

class NqiAchievement(models.Model):
    """NQI ET_ACHIEVEMENT_INFO mirror."""
    _name = 'sn.wsd.nqi.et.achievement'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Achievement'
    _rec_name = 'product_code'

    NQI_REQUIRED = (
        'product_code',
        'make_year',
        'finish_counts',
        'out_put',
        'out_put_value',
        'is_advanced',
        'designed_out_put',
    )

    product_code = fields.Char(index=True)
    make_year = fields.Char()
    finish_counts = fields.Char()
    out_put = fields.Char()
    out_put_value = fields.Char()
    is_advanced = fields.Char()
    designed_out_put = fields.Char()

class NqiCapacity(models.Model):
    """NQI ET_CAPACITY_INFO mirror."""
    _name = 'sn.wsd.nqi.et.capacity'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Capacity'
    _rec_name = 'product_type'

    NQI_REQUIRED = (
        'product_type',
        'create_count_one_year',
    )

    product_type = fields.Char()
    create_count_one_year = fields.Char()

class NqiAsMgt(models.Model):
    """NQI ET_AS_MGT_INFO mirror."""
    _name = 'sn.wsd.nqi.et.as.mgt'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI As Mgt'
    _rec_name = 'file_url'

    NQI_REQUIRED = (
        'file_url',
        'after_sale_servicer_num',
        'in_province_response_time',
        'out_province_response_time',
    )

    file_url = fields.Char()
    after_sale_servicer_num = fields.Char()
    in_province_response_time = fields.Char()
    out_province_response_time = fields.Char()

class NqiAsAgreement(models.Model):
    """NQI ET_AS_AGREEMENT_INFO mirror."""
    _name = 'sn.wsd.nqi.et.as.agreement'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI As Agreement'
    _rec_name = 'create_company'

    NQI_REQUIRED = (
        'enterprise_type',
        'file_url',
        'create_company',
        'create_year',
        'bidding_company',
    )

    enterprise_type_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Enterprise Type',
        domain="[('code_type', '=', 'ENTERPRISE_TYPE')]",
        ondelete='restrict')
    enterprise_type = fields.Char()
    file_url = fields.Char()
    create_company = fields.Char()
    create_year = fields.Char()
    bidding_company = fields.Char()

    @api.onchange('enterprise_type_id')
    def _onchange_enterprise_type_id(self):
        for record in self:
            record.enterprise_type = (record.enterprise_type_id.code_id
                or '')

class NqiStandardSetting(models.Model):
    """NQI ET_STANDARD_SETTING_INFO mirror."""
    _name = 'sn.wsd.nqi.et.standard.setting'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Standard Setting'
    _rec_name = 'standard_name'

    NQI_REQUIRED = (
        'standard_level',
        'standard_code',
        'standard_name',
        'setting_members',
    )

    standard_level = fields.Char()
    standard_code = fields.Char()
    standard_name = fields.Char()
    setting_members = fields.Char()

class NqiRb(models.Model):
    """NQI ET_RB_INFO mirror."""
    _name = 'sn.wsd.nqi.et.rb'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Rb'
    _rec_name = 'make_year'

    NQI_REQUIRED = (
        'make_year',
        'revenue_amt',
        'rd_amt',
        'budget_amt',
        'equipment_amt',
    )

    make_year = fields.Char()
    revenue_amt = fields.Char()
    rd_amt = fields.Char()
    budget_amt = fields.Char()
    equipment_amt = fields.Char()

class NqiQi(models.Model):
    """NQI ET_QI_INFO mirror."""
    _name = 'sn.wsd.nqi.et.qi'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Qi'
    _rec_name = 'improvement_project'

    NQI_REQUIRED = (
        'make_year',
        'improvement_project',
        'train_count',
        'trainees_count',
    )

    make_year = fields.Char()
    improvement_project = fields.Char()
    train_count = fields.Char()
    trainees_count = fields.Char()

class NqiSupplierScore(models.Model):
    """NQI ET_SUPPLYER_SCORE_INFO mirror."""
    _name = 'sn.wsd.nqi.et.supplier.score'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Supplier Score'
    _rec_name = 'supplie_enterprise_code'

    NQI_REQUIRED = (
        'supplie_enterprise_code',
        'make_year',
        'score',
    )

    supplie_enterprise_code = fields.Char()
    make_year = fields.Char()
    score = fields.Char()

class NqiFile(models.Model):
    """NQI PUB_FILE_INFO mirror."""
    _name = 'sn.wsd.nqi.pub.file'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI File'
    _rec_name = 'file_name'

    NQI_REQUIRED = (
        'type',
        'file_url',
        'file_idx',
        'file_name',
        'blob',
    )

    attachment_id = fields.Many2one(
        'ir.attachment', string='Attachment',
        ondelete='set null', index=True, tracking=True)
    type = fields.Char()
    file_url = fields.Char()
    download_url = fields.Char()
    file_idx = fields.Char()
    file_name = fields.Char()
    file_data = fields.Char()
    blob = fields.Char()
