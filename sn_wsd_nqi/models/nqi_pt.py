"""Generated from the NQI data model V2.1 docx (see
build_tmp/nqi_explore/gen_models.py and fields.json)."""
from odoo import fields, models

class NqiPlan(models.Model):
    """NQI PT_PRODUCTION_PLAN mirror."""
    _name = 'sn.wsd.nqi.pt.plan'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Plan'
    _rec_name = 'plan_code'

    NQI_REQUIRED = (
        'plan_code',
        'start_time',
        'finish_time',
        'business_contract_code',
        'product_code',
    )

    sale_order_id = fields.Many2one(
        'sale.order', string='Sales Order',
        ondelete='set null', index=True, tracking=True)
    plan_code = fields.Char(index=True)
    start_time = fields.Char()
    finish_time = fields.Char()
    business_contract_code = fields.Char(index=True)
    product_code = fields.Char(index=True)

    _natural_key_uniq = models.Constraint(
        'unique(company_id, plan_code)',
        'Natural key must be unique per company.')

class NqiPlanDetail(models.Model):
    """NQI PT_PRODUCTION_DETAIL_PLAN mirror."""
    _name = 'sn.wsd.nqi.pt.plan.detail'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Plan Detail'
    _rec_name = 'plan_code'

    NQI_REQUIRED = (
        'plan_code',
        'count',
        'type',
        'start_serial_no',
        'finish_serial_no',
    )

    plan_id = fields.Many2one(
        'sn.wsd.nqi.pt.plan', string='NQI Plan',
        ondelete='set null', index=True, tracking=True)
    plan_code = fields.Char(index=True)
    count = fields.Char()
    type = fields.Char()
    module_type = fields.Char()
    start_serial_no = fields.Char()
    finish_serial_no = fields.Char()

class NqiProcess(models.Model):
    """NQI PT_PRODUCTION_PROCESS mirror."""
    _name = 'sn.wsd.nqi.pt.process'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Process'
    _rec_name = 'plan_code'

    NQI_REQUIRED = (
        'plan_code',
        'bidding_party_a',
        'plan_num',
    )

    plan_code = fields.Char(index=True)
    bidding_party_a_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Bidding Party A',
        domain="[('code_type', '=', 'BIDDING_PARTY_A')]",
        ondelete='restrict')
    bidding_party_a = fields.Char()
    meter_producing_process_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Meter Producing Process Code',
        domain="[('code_type', '=', 'METER_PRODUCING_PROCESS')]",
        ondelete='restrict')
    meter_producing_process_code = fields.Char()
    module_type = fields.Char()
    plan_num = fields.Char()
    finish_num = fields.Char()
    excepiton_handle = fields.Char()

class NqiProcedure(models.Model):
    """NQI PT_PRODUCTION_PROCEDURE mirror."""
    _name = 'sn.wsd.nqi.pt.procedure'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Procedure'
    _rec_name = 'procedure_code'

    NQI_REQUIRED = (
        'procedure_code',
        'plan_code',
        'procedure_name',
    )

    procedure_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Procedure Code',
        domain="[('code_type', '=', 'METER_PRODUCING_PROCESS')]",
        ondelete='restrict')
    procedure_code = fields.Char()
    plan_code = fields.Char(index=True)
    procedure_name = fields.Char()

class NqiEnvTempHum(models.Model):
    """NQI PT_ENV_TEMP_HUM mirror."""
    _name = 'sn.wsd.nqi.pt.env.temp.hum'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Env Temp Hum'
    _rec_name = 'place'

    NQI_REQUIRED = (
        'procedure_code',
        'temperature',
        'humidity',
        'read_date',
    )

    procedure_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Procedure Code',
        domain="[('code_type', '=', 'ENVIRONMENT_TYPE')]",
        ondelete='restrict')
    procedure_code = fields.Char()
    place = fields.Char()
    temperature = fields.Char()
    humidity = fields.Char()
    file_url = fields.Char()
    read_date = fields.Char()

class NqiUnqualified(models.Model):
    """NQI PT_UNQUALIFIED_CONTROL mirror."""
    _name = 'sn.wsd.nqi.pt.unqualified'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Unqualified'
    _rec_name = 'in_control_code'

    NQI_REQUIRED = (
        'serial_no',
        'device_code',
        'operator_code',
        'create_time',
        'procedure_code',
        'fault_phenomena',
        'repair_operator_code',
        'position',
        'unpass_analysis',
        'solution',
        'valid_time',
    )

    in_control_code = fields.Char()
    serial_no = fields.Char(index=True)
    device_code = fields.Char()
    operator_code = fields.Char()
    create_time = fields.Char()
    procedure_code = fields.Char()
    fault_phenomena = fields.Char()
    repair_operator_code = fields.Char()
    position = fields.Char()
    unpass_analysis = fields.Char()
    solution = fields.Char()
    valid_time = fields.Char()
