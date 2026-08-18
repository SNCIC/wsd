from odoo import api, fields, models


class AoiDefectDetail(models.Model):
    _name = 'sn.wsd.aoi.defect.detail'
    _description = 'AOI Defect Detail'
    _order = 'test_result_id, id'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    internal_serial_id = fields.Many2one(
        related='test_result_id.internal_serial_id',
        store=True,
        readonly=True,
        check_company=True,
    )
    production_id = fields.Many2one(
        related='test_result_id.production_id',
        store=True,
        readonly=True,
        check_company=True,
    )
    workorder_id = fields.Many2one(
        related='test_result_id.workorder_id',
        store=True,
        readonly=True,
        check_company=True,
    )
    mes_order_id = fields.Many2one(
        related='test_result_id.mes_order_id',
        store=True,
        readonly=True,
        check_company=True,
    )
    route_operation_id = fields.Many2one(
        related='test_result_id.route_operation_id',
        store=True,
        readonly=True,
        check_company=True,
    )
    workcenter_id = fields.Many2one(
        related='test_result_id.workcenter_id',
        store=True,
        readonly=True,
        check_company=True,
    )
    part_id = fields.Char(index=True)
    position = fields.Char()
    defect_code = fields.Char(required=True, index=True)
    defect_name = fields.Char(required=True)
    confirmed_result = fields.Char(required=True, index=True)
    image_path = fields.Char()
    payload = fields.Json(copy=False)

    @api.depends('part_id', 'defect_code', 'confirmed_result')
    def _compute_name(self):
        for record in self:
            record.name = ' / '.join(filter(None, [
                record.part_id,
                record.defect_code,
                record.confirmed_result,
            ])) or record.defect_code


class MesTestResult(models.Model):
    _inherit = 'sn.wsd.mes.test.result'

    test_type = fields.Selection(selection_add=[('aoi', 'AOI')], ondelete={'aoi': 'set default'})
    aoi_log_code = fields.Char(string='AOI Log Code', index=True, copy=False)
    aoi_machine_name = fields.Char(string='AOI Machine Name', index=True)
    aoi_inspection_type = fields.Char(string='AOI Inspection Type')
    aoi_retest_result = fields.Char(string='AOI Retest Result')
    aoi_station_result = fields.Char(string='AOI Station Result', index=True)
    aoi_station_info = fields.Text(string='AOI Station Info')
    aoi_retest_time = fields.Datetime(string='AOI Retest Time')
    aoi_create_time = fields.Datetime(string='AOI Create Time')
    aoi_file_name = fields.Char(string='AOI File Name')
    aoi_program_name = fields.Char(string='AOI Program Name')
    aoi_small_board_no = fields.Char(string='AOI Small Board No', index=True)
    aoi_total_parts = fields.Integer(string='AOI Total Parts')
    aoi_error_parts = fields.Integer(string='AOI Error Parts')
    aoi_confirmed_defect_parts = fields.Integer(string='AOI Confirmed Defect Parts')
    aoi_face = fields.Char(string='AOI Face')
    aoi_operator = fields.Char(string='AOI Operator', index=True)
    aoi_defect_detail_ids = fields.One2many(
        'sn.wsd.aoi.defect.detail',
        'test_result_id',
        string='AOI Defect Details',
        readonly=True,
    )
    aoi_defect_count = fields.Integer(compute='_compute_aoi_defect_count')

    def _compute_aoi_defect_count(self):
        detail_model = self.env['sn.wsd.aoi.defect.detail']
        for record in self:
            record.aoi_defect_count = detail_model.search_count([('test_result_id', '=', record.id)])
