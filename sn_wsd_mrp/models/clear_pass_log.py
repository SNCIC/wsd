from odoo import fields, models


class SnWsdClearPassLog(models.Model):
    """Audit trail of station-pass clears (清除过站日志).

    One row per clear: who and when live on the native ``create_uid`` /
    ``create_date`` columns, this table keeps what was wiped -- the SN,
    the MES order, how many history rows went away and whether a WIP row
    was deleted with them. Append-only by design: no view, no edit."""
    _name = 'sn.wsd.clear.pass.log'
    _description = 'Station Pass Clear Log'
    _order = 'create_date desc'
    _check_company_auto = True

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True, index=True,
        ondelete='cascade', check_company=True,
    )
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN', required=True, index=True,
        ondelete='restrict',
    )
    serial_name = fields.Char(
        related='serial_identity_id.name', store=True,
    )
    order_name = fields.Char(
        string='MES Order No.', related='mes_order_id.name', store=True,
    )
    cleared_history_count = fields.Integer(
        string='Cleared History Rows',
        help='Station-pass history rows deleted by this clear.',
    )
    cleared_wip = fields.Boolean(
        string='Cleared WIP Row',
        help='True when an in-progress (WIP) row was deleted too.',
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company,
    )
