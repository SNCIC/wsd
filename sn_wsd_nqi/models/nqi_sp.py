"""Generated from the NQI data model V2.1 docx (see
build_tmp/nqi_explore/gen_models.py and fields.json)."""
from odoo import fields, models

class NqiBoxBind(models.Model):
    """NQI SP_BOX_METER_BIND mirror."""
    _name = 'sn.wsd.nqi.sp.box.bind'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Box Bind'
    _rec_name = 'box_code'

    NQI_REQUIRED = (
        'barcode',
        'box_code',
        'device_code',
        'operator_code',
    )

    barcode = fields.Char()
    box_code = fields.Char()
    device_code = fields.Char()
    operator_code = fields.Char()

class NqiSupplyBatch(models.Model):
    """NQI SP_SUPPLY_BATCH mirror."""
    _name = 'sn.wsd.nqi.sp.supply.batch'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Supply Batch'
    _rec_name = 'supply_batch_no'

    NQI_REQUIRED = (
        'business_contract_code',
        'supply_batch_no',
        'supply_num',
        'start_barcode',
        'finish_barcode',
        'supply_date',
    )

    picking_id = fields.Many2one(
        'stock.picking', string='Delivery',
        ondelete='set null', index=True, tracking=True)
    business_contract_code = fields.Char(index=True)
    supply_batch_no = fields.Char()
    supply_num = fields.Char()
    start_number_code = fields.Char()
    end_number_code = fields.Char()
    start_barcode = fields.Char()
    finish_barcode = fields.Char()
    supply_date = fields.Char()

class NqiSupplyTest(models.Model):
    """NQI SP_SUPPLY_TEST mirror."""
    _name = 'sn.wsd.nqi.sp.supply.test'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Supply Test'
    _rec_name = 'supply_batch_no'

    NQI_REQUIRED = (
        'supply_batch_no',
        'start_barcode',
        'finish_barcode',
        'detect_date',
        'file_url',
    )

    supply_batch_no = fields.Char()
    start_barcode = fields.Char()
    finish_barcode = fields.Char()
    detect_date = fields.Char(index=True)
    person_code = fields.Char()
    file_url = fields.Char()

class NqiSpotCheck(models.Model):
    """NQI SP_SPOT_CHECK_RECORD mirror."""
    _name = 'sn.wsd.nqi.sp.spot.check'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Spot Check'
    _rec_name = 'supply_batch_no'

    NQI_REQUIRED = (
        'supply_batch_no',
        'device_code',
        'test_unit',
        'barcode',
        'test_date',
        'test_project',
        'test_result',
    )

    supply_batch_no = fields.Char()
    device_code = fields.Char()
    test_unit = fields.Char()
    barcode = fields.Char()
    test_date = fields.Char()
    test_project = fields.Char()
    test_result = fields.Char()

class NqiRecall(models.Model):
    """NQI SP_METER_RECALL mirror."""
    _name = 'sn.wsd.nqi.sp.recall'
    _inherit = ['mail.thread', 'sn.wsd.nqi.staging.mixin']
    _description = 'NQI Recall'
    _rec_name = 'supply_batch_no'

    NQI_REQUIRED = (
        'supply_batch_no',
        'start_barcode',
        'finish_barcode',
        'unpass_analysis',
        'solution',
    )

    supply_batch_no = fields.Char()
    start_barcode = fields.Char()
    finish_barcode = fields.Char()
    unpass_analysis = fields.Char()
    solution = fields.Char()
