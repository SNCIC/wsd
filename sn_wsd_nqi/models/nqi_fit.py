"""Generated from the NQI data model V2.1 docx (see
build_tmp/nqi_explore/gen_models.py and fields.json)."""
from odoo import api, fields, models

class NqiMeterInfo(models.Model):
    """NQI FIT_METER_INFO mirror."""
    _name = 'sn.wsd.nqi.fit.meter.info'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI Meter Info'
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'make_plan_no',
        'barcode',
        'conc_code',
        'test_date',
        'status',
    )

    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN Identity',
        ondelete='set null', index=True)
    serial_no = fields.Char(index=True)
    make_plan_no = fields.Char()
    assets_code = fields.Char()
    barcode = fields.Char()
    meter_no = fields.Char()
    software_version = fields.Char()
    out_factory_supply = fields.Char()
    conc_code = fields.Char()
    test_date = fields.Char()
    status = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, serial_no)',
        'Natural key must be unique per company.')

class NqiPcbMounting(models.Model):
    """NQI FIT_PCB_MOUNTING_MAKE mirror."""
    _name = 'sn.wsd.nqi.fit.pcb.mounting'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI Pcb Mounting'
    _rec_name = 'pcb_code'

    NQI_REQUIRED = (
        'pcb_code',
        'make_plan_code',
        'para_index',
        'procedure_code',
        'device_code',
        'operator_code',
        'detect_date',
    )

    pcb_code = fields.Char(index=True)
    module_type = fields.Char()
    make_plan_code = fields.Char(index=True)
    para_index = fields.Char()
    procedure_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Procedure Code',
        domain="[('code_type', '=', 'PCB_PRODUCING_PROCESS')]",
        ondelete='restrict')
    procedure_code = fields.Char()
    device_code = fields.Char()
    operator_code = fields.Char()
    detect_date = fields.Char(index=True)

    @api.onchange('procedure_code_id')
    def _onchange_procedure_code_id(self):
        for record in self:
            record.procedure_code = (record.procedure_code_id.code_id
                or '')

class NqiMeterMounting(models.Model):
    """NQI FIT_METER_MOUNTING_MAKE mirror."""
    _name = 'sn.wsd.nqi.fit.meter.mounting'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI Meter Mounting'
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'serial_no',
        'make_plan_code',
        'para_index',
        'procedure_code',
        'operator_code',
        'detect_date',
    )

    serial_no = fields.Char(index=True)
    make_plan_code = fields.Char(index=True)
    para_index = fields.Char()
    procedure_code_id = fields.Many2one(
        'sn.wsd.nqi.code', string='Procedure Code',
        domain="[('code_type', '=', 'METER_PRODUCING_PROCESS')]",
        ondelete='restrict')
    procedure_code = fields.Char()
    device_code = fields.Char()
    operator_code = fields.Char()
    detect_date = fields.Char(index=True)

    @api.onchange('procedure_code_id')
    def _onchange_procedure_code_id(self):
        for record in self:
            record.procedure_code = (record.procedure_code_id.code_id
                or '')

class NqiComponentBind(models.Model):
    """NQI FIT_METER_COMPONENT_BIND mirror."""
    _name = 'sn.wsd.nqi.fit.component.bind'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI Component Bind'
    _rec_name = 'pcb_code'

    NQI_REQUIRED = (
        'pcb_code',
        'plan_code',
        'component_code',
        'make_batch_no',
    )

    pcb_code = fields.Char(index=True)
    module_type = fields.Char()
    plan_code = fields.Char(index=True)
    component_code = fields.Char()
    make_batch_no = fields.Char()

class NqiPcbSerialBind(models.Model):
    """NQI FIT_PCB_SERIAL_BIND mirror."""
    _name = 'sn.wsd.nqi.fit.pcb.serial.bind'
    _inherit = ['sn.wsd.nqi.staging.mixin']
    _description = 'NQI Pcb Serial Bind'
    _rec_name = 'serial_no'

    NQI_REQUIRED = (
        'plan_code',
        'serial_no',
        'pcb_code',
    )

    plan_code = fields.Char(index=True)
    serial_no = fields.Char(index=True)
    pcb_code = fields.Char(index=True)
    module_type = fields.Char()

    _natural_key_uniq = models.Constraint(
        'unique(company_id, plan_code, serial_no, pcb_code)',
        'Natural key must be unique per company.')
