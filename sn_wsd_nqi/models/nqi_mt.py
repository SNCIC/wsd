"""Generated from the NQI data model V2.1 docx (see
build_tmp/nqi_explore/gen_models.py and fields.json)."""
from odoo import fields, models

class Nqi(models.Model):
    """NQI MT_AOI_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_aoi'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'pcb_code'

    NQI_REQUIRED = (
        'pcb_code',
        'detect_date',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    pcb_code = fields.Char(index=True)
    module_type = fields.Char()
    detect_date = fields.Char(index=True)
    conc_code = fields.Char()
    cause = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, pcb_code, detect_date)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_BASICERR_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_basicerr'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'both_way_power_flag',
        'iabc',
        'load_current',
        'load_voltage',
        'freq',
        'pf',
        'detect_circle',
        'simpling',
        'error_number',
        'error',
        'ave_err',
        'int_convert_err',
        'conc_code',
        'err_up',
        'err_down',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    iabc_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Iabc',
        domain="[('code_type', '=', 'PHASE_CURRENT')]",
        ondelete='restrict')
    iabc = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    load_voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Voltage',
        domain="[('code_type', '=', 'METER_PARA_VOLTAGE')]",
        ondelete='restrict')
    load_voltage = fields.Char()
    freq_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Freq',
        domain="[('code_type', '=', 'METER_PARA_FREQ')]",
        ondelete='restrict')
    freq = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    detect_circle = fields.Char()
    simpling = fields.Char()
    error_number = fields.Char()
    error = fields.Char()
    ave_err = fields.Char()
    int_convert_err = fields.Char()
    conc_code = fields.Char()
    err_up = fields.Char()
    err_down = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_CONST_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_const'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'load_current',
        'both_way_power_flag',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    real_pules = fields.Char()
    start_reading = fields.Char()
    end_reading = fields.Char()
    diff_reading = fields.Char()
    standard_reading = fields.Char()
    error = fields.Char()
    err_down = fields.Char()
    err_up = fields.Char()
    const_err = fields.Char()
    volt = fields.Char()
    fee_start_time = fields.Char()
    fee_ratio = fields.Char()
    qualified_pules = fields.Char()
    divide_electric_quantity = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    control_method_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Control Method',
        domain="[('code_type', '=', 'RATE_CONTROL_TYPE')]",
        ondelete='restrict')
    control_method = fields.Char()
    conc_code = fields.Char()
    ir_last_reading = fields.Char()
    read_type_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Read Type Code',
        domain="[('code_type', '=', 'READ_TYPE_CODE')]",
        ondelete='restrict')
    read_type_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_CREEPING_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_creeping'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'load_voltage',
        'pules',
        'load_current',
        'both_way_power_flag',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    load_voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Voltage',
        domain="[('code_type', '=', 'METER_PARA_VOLTAGE')]",
        ondelete='restrict')
    load_voltage = fields.Char()
    pules = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    test_time = fields.Char()
    real_test_time = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_DAYERR_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_dayerr'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'sec_piles',
        'test_time',
        'simpling',
        'err_abs',
        'error',
        'avg_err',
        'int_convert_err',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    sec_piles = fields.Char()
    test_time = fields.Char()
    simpling = fields.Char()
    err_abs = fields.Char()
    load_voltage = fields.Char()
    error = fields.Char()
    avg_err = fields.Char()
    int_convert_err = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_DEMANDVALUE_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_demandvalue'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'both_way_power_flag',
        'voltage',
        'load_current',
        'pf',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    demand_period = fields.Char()
    demand_time = fields.Char()
    demand_interval = fields.Char()
    real_demand = fields.Char()
    real_period = fields.Char()
    demand_value_err = fields.Char()
    demand_standard = fields.Char()
    demand_value_err_abs = fields.Char()
    clear_data_rst = fields.Char()
    value_conc_code = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Voltage',
        domain="[('code_type', '=', 'METER_TEST_VOLT')]",
        ondelete='restrict')
    voltage = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    control_method_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Control Method',
        domain="[('code_type', '=', 'RATE_CONTROL_TYPE')]",
        ondelete='restrict')
    control_method = fields.Char()
    err_up = fields.Char()
    err_dowm = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_ESAM_READ_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_esam_read'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'conc_code',
        'test_item',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    conc_code = fields.Char()
    load_voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Voltage',
        domain="[('code_type', '=', 'METER_PARA_VOLTAGE')]",
        ondelete='restrict')
    load_voltage = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    test_item = fields.Char()
    test_method_differ = fields.Char()
    trip_delay_time = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_FUNCTION_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_function'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'function_type',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    function_type = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_HUTCHISON_COMBINA_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_hutchison_combina'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'both_way_power_flag',
        'load_current',
        'pf',
        'fee_ratio',
        'control_method',
        'ir_time',
        'ir_reading',
        'err_down',
        'err_up',
        'voltage',
        'total_reading_err',
        'total_increment',
        'sumer_all_increment',
        'sharp_increment',
        'peak_increment',
        'flat_increment',
        'valley_increment',
        'value_conc_code',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    fee_ratio = fields.Char()
    control_method_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Control Method',
        domain="[('code_type', '=', 'RATE_CONTROL_TYPE')]",
        ondelete='restrict')
    control_method = fields.Char()
    ir_time = fields.Char()
    ir_reading = fields.Char()
    err_down = fields.Char()
    err_up = fields.Char()
    voltage = fields.Char()
    total_reading_err = fields.Char()
    total_increment = fields.Char()
    sumer_all_increment = fields.Char()
    sharp_increment = fields.Char()
    peak_increment = fields.Char()
    flat_increment = fields.Char()
    valley_increment = fields.Char()
    value_conc_code = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_INTUIT_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_intuit'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'detect_content',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    detect_content = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_MOUNTING_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_mounting'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'make_plan_code',
        'test_type',
        'test_project',
        'detect_date',
        'test_result',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    pcb_code = fields.Char(index=True)
    module_type = fields.Char()
    make_plan_code = fields.Char(index=True)
    device_code = fields.Char()
    operator_code = fields.Char()
    position_no = fields.Char()
    test_type = fields.Char()
    test_project = fields.Char()
    detect_date = fields.Char(index=True)
    test_result = fields.Char()
    cause = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, pcb_code, detect_date)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_PARAMETER_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_parameter'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'plan_code',
        'serial_no',
        'test_type',
        'operator_code',
        'detect_date',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    plan_code = fields.Char(index=True)
    serial_no = fields.Char(index=True)
    test_type = fields.Char()
    test_name = fields.Char()
    operator_code = fields.Char()
    detect_date = fields.Char(index=True)
    conc_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Conc Code',
        domain="[('code_type', '=', 'TEST_RESULT')]",
        ondelete='restrict')
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_RFID_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_rfid'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'rfid_code',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    rfid_code = fields.Char()
    conc_code = fields.Char()
    cause = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_SINGLE_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_single'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'pcb_code'

    NQI_REQUIRED = (
        'pcb_code',
        'detect_date',
        'test_project',
        'test_data',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    pcb_code = fields.Char(index=True)
    module_type = fields.Char()
    detect_date = fields.Char(index=True)
    test_project = fields.Char()
    test_data = fields.Char()
    conc_code = fields.Char()
    cause = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, pcb_code, detect_date)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_STARTING_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_starting'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'load_voltage',
        'pules',
        'both_way_power_flag',
        'load_current',
        'start_current',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    load_voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Voltage',
        domain="[('code_type', '=', 'METER_PARA_VOLTAGE')]",
        ondelete='restrict')
    load_voltage = fields.Char()
    pules = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    test_time = fields.Char()
    real_test_time = fields.Char()
    start_current = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_TIME_ERROR_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_time_error'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_TS_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_ts'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    ts_err_conc_code = fields.Char()
    conc_code = fields.Char()
    volt_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Volt',
        domain="[('code_type', '=', 'METER_TEST_VOLT')]",
        ondelete='restrict')
    volt = fields.Char()
    ts_way = fields.Char()
    start_time = fields.Char()
    ts_start_time = fields.Char()
    ts_err = fields.Char()
    err_up = fields.Char()
    err_dowm = fields.Char()
    ts_real_time = fields.Char()
    fee = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI MT_VOLT_CONC mirror."""
    _name = 'sn.wsd.nqi.mt_volt'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_item_point',
        'volt_test_value',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    detect_item_point = fields.Char()
    volt_test_value = fields.Char()
    test_time = fields.Char()
    conc_code = fields.Char()
    cause = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI OT_OTHER_CONC mirror."""
    _name = 'sn.wsd.nqi.ot_other'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'pcb_code',
        'test_name',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    pcb_code = fields.Char(index=True)
    test_name = fields.Char()
    conc_code = fields.Char()
    cause = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, pcb_code)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_CONSIST_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_consist'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'both_way_power_flag',
        'load_voltage',
        'load_current',
        'pf',
        'pules',
        'simpling',
        'all_error',
        'avg_error',
        'int_convert_err',
        'all_avg_error',
        'all_int_error',
        'error',
        'err_down',
        'err_up',
        'once_err',
        'avg_once_err',
        'int_once_err',
        'twice_err',
        'avg_twice_err',
        'int_twice_err',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    load_voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Voltage',
        domain="[('code_type', '=', 'METER_PARA_VOLTAGE')]",
        ondelete='restrict')
    load_voltage = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    pules = fields.Char()
    simpling = fields.Char()
    all_error = fields.Char()
    avg_error = fields.Char()
    int_convert_err = fields.Char()
    all_avg_error = fields.Char()
    all_int_error = fields.Char()
    error = fields.Char()
    err_down = fields.Char()
    err_up = fields.Char()
    once_err = fields.Char()
    avg_once_err = fields.Char()
    int_once_err = fields.Char()
    twice_err = fields.Char()
    avg_twice_err = fields.Char()
    int_twice_err = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_DEMAND_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_demand'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'demand_period',
        'demand_time',
        'demand_interval',
        'real_demand',
        'real_period',
        'demand_period_err',
        'demand_standard',
        'demand_period_err_abs',
        'clear_data_rst',
        'period_conc_code',
        'both_way_power_flag',
        'control_method',
        'load_current',
        'voltage',
        'freq',
        'pf',
        'err_up',
        'err_dowm',
        'int_convert_err',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    demand_period = fields.Char()
    demand_time = fields.Char()
    demand_interval = fields.Char()
    real_demand = fields.Char()
    real_period = fields.Char()
    demand_period_err = fields.Char()
    demand_standard = fields.Char()
    demand_period_err_abs = fields.Char()
    clear_data_rst = fields.Char()
    period_conc_code = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    control_method = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Voltage',
        domain="[('code_type', '=', 'METER_TEST_VOLT')]",
        ondelete='restrict')
    voltage = fields.Char()
    freq_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Freq',
        domain="[('code_type', '=', 'METER_PARA_FREQ')]",
        ondelete='restrict')
    freq = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    err_up = fields.Char()
    err_dowm = fields.Char()
    int_convert_err = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_EQ_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_eq'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'total_eq',
        'surplus_eq',
        'curr_elec_price',
        'load_current',
        'pf',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    total_eq = fields.Char()
    surplus_eq = fields.Char()
    curr_elec_price = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_ERROR_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_error'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'both_way_power_flag',
        'load_voltage',
        'load_current',
        'pf',
        'pules',
        'simpling',
        'once_err',
        'avg_once_err',
        'int_once_err',
        'twice_err',
        'avg_twice_err',
        'error',
        'err_down',
        'err_up',
        'int_twice_err',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    load_voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Voltage',
        domain="[('code_type', '=', 'METER_PARA_VOLTAGE')]",
        ondelete='restrict')
    load_voltage = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    pules = fields.Char()
    simpling = fields.Char()
    once_err = fields.Char()
    avg_once_err = fields.Char()
    int_once_err = fields.Char()
    twice_err = fields.Char()
    avg_twice_err = fields.Char()
    error = fields.Char()
    err_down = fields.Char()
    err_up = fields.Char()
    int_twice_err = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_EVENT_RECORD_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_event_record'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'load_current',
        'pf',
        'simpling',
        'overload_time',
        'recover_time',
        'err_up',
        'err_down',
        'conc_code',
        'ir_pules',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    simpling = fields.Char()
    overload_time = fields.Char()
    recover_time = fields.Char()
    err_up = fields.Char()
    err_down = fields.Char()
    conc_code = fields.Char()
    ir_pules = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_FEE_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_fee'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'conc_code',
        'pf',
        'cur_phase_code',
        'load_current',
        'both_way_power_flag',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    conc_code = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    cur_phase_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Cur Phase Code',
        domain="[('code_type', '=', 'PHASE_CURRENT')]",
        ondelete='restrict')
    cur_phase_code = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_MAX_DEMANDVALUE_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_max_demandvalue'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'conc_code',
        'cur_phase_code',
        'load_current',
        'both_way_power_flag',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    conc_code = fields.Char()
    cur_phase_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Cur Phase Code',
        domain="[('code_type', '=', 'PHASE_CURRENT')]",
        ondelete='restrict')
    cur_phase_code = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_MAX_DEMAND_ERR_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_max_demand_err'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'load_current',
        'load_voltage',
        'freq',
        'pf',
        'error',
        'avg_err',
        'int_convert_err',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    load_voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Voltage',
        domain="[('code_type', '=', 'METER_PARA_VOLTAGE')]",
        ondelete='restrict')
    load_voltage = fields.Char()
    freq_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Freq',
        domain="[('code_type', '=', 'METER_PARA_FREQ')]",
        ondelete='restrict')
    freq = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    error = fields.Char()
    avg_err = fields.Char()
    int_convert_err = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_OVERLOAD_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_overload'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'load_voltage',
        'load_current',
        'pf',
        'pules',
        'simpling',
        'overload_time',
        'wait_time',
        'error',
        'err_down',
        'err_up',
        'avg_err',
        'int_converter_err',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    load_voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Voltage',
        domain="[('code_type', '=', 'METER_PARA_VOLTAGE')]",
        ondelete='restrict')
    load_voltage = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    pules = fields.Char()
    simpling = fields.Char()
    overload_time = fields.Char()
    wait_time = fields.Char()
    error = fields.Char()
    err_down = fields.Char()
    err_up = fields.Char()
    avg_err = fields.Char()
    int_converter_err = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_POWER_MEASURE_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_power_measure'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'conc_code',
        'cur_phase_code',
        'consist_down',
        'consist_up',
        'volt_ratio',
        'err_down',
        'err_up',
        'simpling_space',
        'simpling',
        'pf',
        'load_current',
        'both_way_power_flag',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    conc_code = fields.Char()
    cur_phase_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Cur Phase Code',
        domain="[('code_type', '=', 'PHASE_CURRENT')]",
        ondelete='restrict')
    cur_phase_code = fields.Char()
    consist_down = fields.Char()
    consist_up = fields.Char()
    volt_ratio = fields.Char()
    err_down = fields.Char()
    err_up = fields.Char()
    simpling_space = fields.Char()
    simpling = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_STANDARD_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_standard'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'data_flag',
        'detect_basis',
        'setting_value',
        'read_value',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    data_flag = fields.Char()
    detect_basis = fields.Char()
    setting_value = fields.Char()
    read_value = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')

class Nqi(models.Model):
    """NQI TT_VARIATION_CONC mirror."""
    _name = 'sn.wsd.nqi.tt_variation'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI '
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'detect_date',
        'para_index',
        'detect_item_point',
        'both_way_power_flag',
        'load_voltage',
        'load_current',
        'iabc',
        'pf',
        'detect_circle',
        'simpling',
        'wait_time',
        'up_err1',
        'up_err2',
        'avg_up_err',
        'int_up_err',
        'down_err1',
        'down_err2',
        'avg_down_err',
        'int_down_err',
        'variation_err',
        'int_variation_err',
        'conc_code',
    )

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='MES Test Result',
        ondelete='set null', index=True, tracking=True)
    serial_no = fields.Char(index=True)
    detect_date = fields.Char(index=True)
    para_index = fields.Char()
    detect_item_point = fields.Char()
    both_way_power_flag_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Both Way Power Flag',
        domain="[('code_type', '=', 'METER_PARA_POWER_FLAG')]",
        ondelete='restrict')
    both_way_power_flag = fields.Char()
    load_voltage_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Voltage',
        domain="[('code_type', '=', 'METER_PARA_VOLTAGE')]",
        ondelete='restrict')
    load_voltage = fields.Char()
    load_current_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Load Current',
        domain="[('code_type', '=', 'METER_TEST_CURLOAD')]",
        ondelete='restrict')
    load_current = fields.Char()
    iabc_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Iabc',
        domain="[('code_type', '=', 'PHASE_CURRENT')]",
        ondelete='restrict')
    iabc = fields.Char()
    pf_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Pf',
        domain="[('code_type', '=', 'METER_PARA_PF_RATE')]",
        ondelete='restrict')
    pf = fields.Char()
    detect_circle = fields.Char()
    simpling = fields.Char()
    wait_time = fields.Char()
    up_err1 = fields.Char()
    up_err2 = fields.Char()
    avg_up_err = fields.Char()
    int_up_err = fields.Char()
    down_err1 = fields.Char()
    down_err2 = fields.Char()
    avg_down_err = fields.Char()
    int_down_err = fields.Char()
    variation_err = fields.Char()
    int_variation_err = fields.Char()
    conc_code = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no, detect_date, para_index, detect_item_point)',
        'Natural key must be unique per company.')
