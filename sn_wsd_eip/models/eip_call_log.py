from odoo import fields, models

from .eip_transport import MAX_LOG_TEXT


class EipCallLogMixin(models.AbstractModel):
    """Common columns of the two call logs (pull / push): exactly one
    row per outbound HTTP request, whatever the outcome."""
    _name = 'sn.wsd.eip.call.log.mixin'
    _description = 'EIP Call Log Common Fields'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        ondelete='restrict', readonly=True)
    config_id = fields.Many2one(
        'sn.wsd.eip.config', string='Integration Config', required=True,
        index=True, ondelete='restrict', readonly=True,
        help='The config the call was made under; archive configs '
             'instead of deleting them so logs keep their trace.')
    interface_id = fields.Many2one(
        'sn.wsd.eip.interface', string='Interface', required=True,
        index=True, ondelete='restrict', readonly=True)
    operatetype = fields.Char(
        string='Operation Type', required=True, readonly=True,
        help='operatetype header literal actually sent.')
    transno = fields.Char(
        string='Transaction Number', required=True, index=True,
        readonly=True)
    request_headers = fields.Text(
        string='Request Headers', readonly=True)
    request_body = fields.Text(string='Request Body', readonly=True)
    response_body = fields.Text(
        string='Response Body', readonly=True,
        help='Truncated when longer than %s characters.' % MAX_LOG_TEXT)
    http_status = fields.Integer(string='HTTP Status', readonly=True)
    status_code = fields.Char(string='EIP Status', readonly=True)
    status_message = fields.Char(string='EIP Message', readonly=True)
    result = fields.Selection(
        [('sending', 'Sending'), ('success', 'Success'),
         ('failed', 'Failed')],
        string='Result', required=True, default='sending', index=True,
        readonly=True)
    error = fields.Text(string='Error', readonly=True)
    duration_ms = fields.Integer(string='Duration (ms)', readonly=True)
    start_at = fields.Datetime(
        string='Started At', default=fields.Datetime.now, readonly=True)
    end_at = fields.Datetime(string='Ended At', readonly=True)


class EipPushLog(models.Model):
    """One row per push request; points at the business document it
    carried so every document can open its own history."""
    _name = 'sn.wsd.eip.push.log'
    _description = 'EIP Push Log'
    _inherit = 'sn.wsd.eip.call.log.mixin'
    _order = 'start_at desc, id desc'

    model_name = fields.Char(
        string='Document Model', index=True, readonly=True)
    res_id = fields.Integer(string='Document ID', index=True, readonly=True)
    document_ref = fields.Char(
        string='Document', readonly=True,
        help='Human-readable key of the pushed document (order number).')


class EipPullLog(models.Model):
    """One row per purchase-order pull request (one page)."""
    _name = 'sn.wsd.eip.pull.log'
    _description = 'EIP Pull Log'
    _inherit = 'sn.wsd.eip.call.log.mixin'
    _order = 'start_at desc, id desc'

    page_num = fields.Integer(string='Page', readonly=True)
    filters = fields.Text(string='Query Filters', readonly=True)
    row_count = fields.Integer(string='Rows', readonly=True)
    page_info = fields.Char(string='Paging Info', readonly=True)
