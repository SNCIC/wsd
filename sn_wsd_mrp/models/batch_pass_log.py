from odoo import _, api, fields, models
from odoo.exceptions import AccessError

BATCH_PASS_REASONS = [
    ('equipment_failure', 'Equipment Failure'),
    ('outsourcing', 'Outsourcing'),
    ('process_waiver', 'Temporary Process Waiver'),
    ('other', 'Other'),
]


class SnWsdBatchPassLog(models.Model):
    """Audit trail of batch station passes (批量过站 / 行政过站).

    One row per batch: who and when live on the native ``create_uid`` /
    ``create_date`` columns, this header keeps the deliberate decision --
    the target operation, the reason category, the note and the SN list.
    Every history row written by the batch carries ``x_batch_pass_log_id``
    so administrative passes stay distinguishable from physical scans.
    Append-only by design."""
    _name = 'sn.wsd.batch.pass.log'
    _description = 'Batch Station Pass Log'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True, index=True,
        ondelete='cascade', check_company=True,
    )
    order_name = fields.Char(
        related='mes_order_id.name', store=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Operation', required=True,
        index=True, ondelete='cascade', check_company=True,
    )
    operation_label = fields.Char(
        related='route_operation_id.display_label',
    )
    reason = fields.Selection(
        BATCH_PASS_REASONS, string='Reason', required=True, index=True,
    )
    note = fields.Char(string='Note')
    serial_identity_ids = fields.Many2many(
        'sn.wsd.serial.identity',
        'sn_wsd_batch_pass_log_serial_rel', 'log_id', 'serial_identity_id',
        string='Serials', check_company=True,
    )
    serial_count = fields.Integer(
        string='Serial Count', compute='_compute_serial_count', store=True,
    )
    history_ids = fields.One2many(
        'sn.wsd.serial.operation.history', 'x_batch_pass_log_id',
        string='Pass Rows',
    )
    history_count = fields.Integer(
        string='Pass Row Count', compute='_compute_history_count',
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company,
    )

    def unlink(self):
        # 批量过站日志只增不改不删（与清除过站日志同口径）。
        raise AccessError(_('Batch station pass logs are append-only.'))

    @api.depends('serial_identity_ids')
    def _compute_serial_count(self):
        for log in self:
            log.serial_count = len(log.serial_identity_ids)

    def _compute_history_count(self):
        for log in self:
            log.history_count = len(log.history_ids)
