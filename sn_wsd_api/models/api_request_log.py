from odoo import fields, models


class SnWsdApiRequestLog(models.Model):
    """Full raw record of every device-API call: payload as uploaded,
    response summary, timing. The troubleshooting page."""
    _name = 'sn.wsd.api.request.log'
    _description = 'Device API Request Log'
    _order = 'id desc'
    _rec_name = 'display_ref'

    display_ref = fields.Char(compute='_compute_display_ref')
    endpoint = fields.Char(required=True, index=True,
                           help='API path, e.g. /api/v1/scan-pass')
    request_time = fields.Datetime(default=fields.Datetime.now, required=True,
                                   index=True)
    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda self: self.env.company,
                                 index=True)
    workcenter_code = fields.Char(index=True)
    employee_code = fields.Char(index=True)
    sn = fields.Char(index=True,
                     help='Main SN of the call (panel: the scanned board).')
    result_code = fields.Char(help='HTTP-ish result code of the response.')
    result_message = fields.Char()
    duration_ms = fields.Integer()
    payload = fields.Json(help='The uploaded form, verbatim.')
    response = fields.Json(help='Response body summary.')
    test_result = fields.Selection(
        [('ok', 'OK'), ('ng', 'NG')], index=True)

    def _compute_display_ref(self):
        for log in self:
            log.display_ref = '%s / %s / %s' % (
                log.endpoint, log.sn or '-', log.request_time)

    def action_open_test_results(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Test Results',
            'res_model': 'sn.wsd.mes.test.result',
            'view_mode': 'list,form',
            'domain': [('serial_identity_id.name', '=', self.sn)],
        }
