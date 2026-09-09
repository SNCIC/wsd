"""Verbatim AOI defect lines for the /api/v1/aoi/results upload."""

from odoo import fields, models


class AoiDefectDetail(models.Model):
    """Component-level AOI defect line. Stored verbatim from the device
    upload (no dictionary validation); the dictionary-backed defect used by
    the NG station-pass path sits on the test-result header."""
    _name = 'sn.wsd.aoi.defect.detail'
    _description = 'AOI Defect Detail'
    _order = 'test_result_id, sequence, id'
    _rec_name = 'defect_code'
    _check_company_auto = True

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result',
        string='Test Result',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='test_result_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity',
        string='SN',
        related='test_result_id.serial_identity_id',
        store=True,
        readonly=True,
        index=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='test_result_id.mes_order_id',
        store=True,
        readonly=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        related='test_result_id.workcenter_id',
        store=True,
        readonly=True,
    )
    test_time = fields.Datetime(
        string='Test Time',
        related='test_result_id.test_time',
        store=True,
        readonly=True,
    )
    sequence = fields.Integer(string='Sequence', default=1, required=True)
    part_id = fields.Char(string='Part ID', index=True)
    position = fields.Char(string='Position')
    defect_code = fields.Char(string='Defect Code', index=True)
    defect_name = fields.Char(string='Defect Name')
    confirmed_result = fields.Char(string='Confirmed Result', index=True)
    image_path = fields.Char(string='Image Path')
    payload = fields.Json(string='Raw Detail')
