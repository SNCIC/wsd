from odoo import api, fields, models


class InternalSerial(models.Model):
    _inherit = 'sn.wsd.internal.serial'

    x_nameplate_code = fields.Char(string='Nameplate Code', index=True, copy=False)
    x_mes_repair_state = fields.Selection(
        [
            ('none', 'None'),
            ('repair_required', 'Repair Required'),
            ('repairing', 'Repairing'),
            ('rework', 'Rework'),
        ],
        string='MES Repair State',
        default='none',
        index=True,
        copy=False,
    )
    mes_travel_ids = fields.One2many(
        'sn.wsd.mes.sn.travel',
        'internal_serial_id',
        string='MES Travel History',
        readonly=True,
    )
    mes_test_result_ids = fields.One2many(
        'sn.wsd.mes.test.result',
        'internal_serial_id',
        string='MES Test Results',
        readonly=True,
    )
    test_result_count = fields.Integer(compute='_compute_api_counts')
    travel_count = fields.Integer(compute='_compute_api_counts')

    def _compute_api_counts(self):
        travel_model = self.env['sn.wsd.mes.sn.travel']
        test_model = self.env['sn.wsd.mes.test.result']
        for record in self:
            record.travel_count = travel_model.search_count([('internal_serial_id', '=', record.id)])
            record.test_result_count = test_model.search_count([('internal_serial_id', '=', record.id)])

    def _mark_rework_started(self):
        for record in self:
            record.x_mes_repair_state = 'rework'

    def _mark_rework_step_passed(self):
        for record in self:
            record.x_mes_repair_state = 'none'
