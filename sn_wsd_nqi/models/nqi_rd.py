"""Generated from the NQI data model V2.1 docx (see
build_tmp/nqi_explore/gen_models.py and fields.json)."""
from odoo import api, fields, models

class NqiProductInfo(models.Model):
    """NQI RD_PRODUCT_INFO mirror."""
    _name = 'sn.wsd.nqi.rd.product.info'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Product Info'
    _rec_name = 'product_code'

    NQI_REQUIRED = (
        'product_code',
        'product_type',
        'product_name',
        'product_categid',
        'product_design_basis',
    )

    product_id = fields.Many2one(
        'product.product', string='Product',
        ondelete='set null', index=True, tracking=True)
    product_code = fields.Char(index=True)
    product_type = fields.Char()
    product_name = fields.Char()
    product_categid_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Product Categid',
        domain="[('code_type', '=', 'PRODUCT_CATEGID')]",
        ondelete='restrict')
    product_categid = fields.Char()
    product_design_basis = fields.Char()
    remarks = fields.Text()

    @api.onchange('product_categid_id')
    def _onchange_product_categid_id(self):
        for record in self:
            record.product_categid = (record.product_categid_id.code_id
                or '')

    _natural_key_uniq = models.Constraint(
        'unique(company_id, product_code)',
        'Natural key must be unique per company.')

class NqiProductDetail(models.Model):
    """NQI RD_PRODUCT_DETAIL mirror."""
    _name = 'sn.wsd.nqi.rd.product.detail'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Product Detail'
    _rec_name = 'product_detail_code'

    NQI_REQUIRED = (
        'product_detail_code',
        'product_detail_name',
        'product_code',
        'development_project_no',
        'product_spec',
        'rated_voltage',
        'lcd_integer_digits',
        'lcd_decimal_digits',
        'local_comm_type',
        'remote_comm_type',
        'rate_control_type',
        'technology_rules',
        'file_url',
    )

    product_id = fields.Many2one(
        'product.product', string='Product',
        ondelete='set null', index=True, tracking=True)
    product_detail_code = fields.Char()
    product_detail_name = fields.Char()
    product_code = fields.Char(index=True)
    development_project_no = fields.Char()
    product_spec_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Product Spec',
        domain="[('code_type', '=', 'METER_SPEC')]",
        ondelete='restrict')
    product_spec = fields.Char()
    rated_voltage = fields.Char()
    min_current = fields.Char()
    turn_current = fields.Char()
    rated_current = fields.Char()
    max_current = fields.Char()
    act_pwr_accuracy_grade = fields.Char()
    active_power_constant = fields.Char()
    lcd_integer_digits = fields.Char()
    lcd_decimal_digits = fields.Char()
    local_comm_type = fields.Char()
    remote_comm_type_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Remote Comm Type',
        domain="[('code_type', '=', 'REMOTE_COMM_TYPE')]",
        ondelete='restrict')
    remote_comm_type = fields.Char()
    rate_control_type_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Rate Control Type',
        domain="[('code_type', '=', 'RATE_CONTROL_TYPE')]",
        ondelete='restrict')
    rate_control_type = fields.Char()
    technology_rules = fields.Char()
    file_url = fields.Char()
    remarks = fields.Text()

    @api.onchange('product_spec_id')
    def _onchange_product_spec_id(self):
        for record in self:
            record.product_spec = (record.product_spec_id.code_id
                or '')

    @api.onchange('remote_comm_type_id')
    def _onchange_remote_comm_type_id(self):
        for record in self:
            record.remote_comm_type = (record.remote_comm_type_id.code_id
                or '')

    @api.onchange('rate_control_type_id')
    def _onchange_rate_control_type_id(self):
        for record in self:
            record.rate_control_type = (record.rate_control_type_id.code_id
                or '')

class NqiProductTestReport(models.Model):
    """NQI RD_PRODUCT_TEST_REPORT mirror."""
    _name = 'sn.wsd.nqi.rd.product.test.report'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Product Test Report'
    _rec_name = 'product_code'

    NQI_REQUIRED = (
        'product_code',
        'test_report_code',
        'test_type',
        'test_organization',
        'report_date',
        'witness_material_url',
    )

    product_id = fields.Many2one(
        'product.product', string='Product',
        ondelete='set null', index=True, tracking=True)
    product_code = fields.Char(index=True)
    product_detail_code = fields.Char()
    development_project_no = fields.Char()
    test_report_code = fields.Char()
    test_type_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Test Type',
        domain="[('code_type', '=', 'TEST_TYPE')]",
        ondelete='restrict')
    test_type = fields.Char()
    test_organization = fields.Char()
    report_date = fields.Char()
    report_valid_date = fields.Char()
    witness_material_url = fields.Char()

    @api.onchange('test_type_id')
    def _onchange_test_type_id(self):
        for record in self:
            record.test_type = (record.test_type_id.code_id
                or '')

class NqiProject(models.Model):
    """NQI RD_PROJECT mirror."""
    _name = 'sn.wsd.nqi.rd.project'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Project'
    _rec_name = 'development_project_no'

    NQI_REQUIRED = (
        'development_project_no',
        'product_name',
        'change_count',
    )

    product_id = fields.Many2one(
        'product.product', string='Product',
        ondelete='set null', index=True, tracking=True)
    development_project_no = fields.Char()
    product_code = fields.Char(index=True)
    product_name = fields.Char()
    product_type = fields.Char()
    product_design_function_basis = fields.Char()
    review_count = fields.Char()
    change_count = fields.Char()
    test_count = fields.Char()
    files_count = fields.Char()
    sources_demand = fields.Char()
    file_path = fields.Char()

class NqiProjectDetail(models.Model):
    """NQI RD_PROJECT_DETAIL mirror."""
    _name = 'sn.wsd.nqi.rd.project.detail'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Project Detail'
    _rec_name = 'development_project_no'

    NQI_REQUIRED = (
        'development_project_no',
        'software_version',
        'hardware_version',
    )

    development_project_no = fields.Char()
    module_type = fields.Char()
    software_version = fields.Char()
    hardware_version = fields.Char()

class NqiComponentList(models.Model):
    """NQI RD_COMPONENT_DETAIL_LIST mirror."""
    _name = 'sn.wsd.nqi.rd.component.list'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Component List'
    _rec_name = 'product_code'

    NQI_REQUIRED = (
        'comment_project_no',
        'development_project_no',
        'hardware_version',
        'component_code',
        'component_position',
    )

    product_id = fields.Many2one(
        'product.product', string='Product',
        ondelete='set null', index=True, tracking=True)
    bom_id = fields.Many2one(
        'mrp.bom', string='BoM',
        ondelete='set null', index=True, tracking=True)
    comment_project_no = fields.Char()
    product_code = fields.Char(index=True)
    product_detail_code = fields.Char()
    module_type = fields.Char()
    development_project_no = fields.Char()
    hardware_version = fields.Char()
    component_code = fields.Char()
    component_position = fields.Char()

class NqiProjectChange(models.Model):
    """NQI RD_PROJECT_CHANGE_RECOND mirror."""
    _name = 'sn.wsd.nqi.rd.project.change'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Project Change'
    _rec_name = 'change_type'

    NQI_REQUIRED = (
        'change_type',
        'change_content',
        'change_result',
        'change_time',
        'change_scheme',
        'development_project_no',
        'old_software_version',
        'new_software_version',
        'old_hardware_version',
        'new_hardware_version',
    )

    product_id = fields.Many2one(
        'product.product', string='Product',
        ondelete='set null', index=True, tracking=True)
    change_type = fields.Char()
    change_content = fields.Text()
    change_result = fields.Char()
    change_time = fields.Char()
    change_scheme = fields.Char()
    development_project_no = fields.Char()
    module_type = fields.Char()
    old_software_version = fields.Char()
    new_software_version = fields.Char()
    old_hardware_version = fields.Char()
    new_hardware_version = fields.Char()

class NqiComponentChange(models.Model):
    """NQI RD_COMPONENT_CHANGE_RECORD mirror."""
    _name = 'sn.wsd.nqi.rd.component.change'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Component Change'
    _rec_name = 'change_record_code'

    NQI_REQUIRED = (
        'change_record_code',
        'development_project_no',
        'product_code',
        'product_detail_code',
        'supplier_enterprise_code',
        'change_reason',
        'old_component_position',
        'old_component_code',
        'new_component_position',
        'new_component_code',
    )

    product_id = fields.Many2one(
        'product.product', string='Product',
        ondelete='set null', index=True, tracking=True)
    change_record_code = fields.Char(index=True)
    development_project_no = fields.Char()
    module_type = fields.Char()
    product_code = fields.Char(index=True)
    product_detail_code = fields.Char()
    business_contract_code = fields.Char(index=True)
    plan_code = fields.Char(index=True)
    supplier_enterprise_code = fields.Char()
    change_reason = fields.Char()
    witness_material = fields.Char()
    old_component_position = fields.Char()
    old_component_code = fields.Char()
    new_component_position = fields.Char()
    new_component_code = fields.Char()
