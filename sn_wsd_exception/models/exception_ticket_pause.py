from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .exception_ticket import PAUSE_REASON_SELECTION


class SnWsdExceptionTicketPause(models.Model):
    _name = 'sn.wsd.exception.ticket.pause'
    _description = 'SN WSD Exception Ticket Suspension'
    _order = 'ticket_id, started_at, id'
    _check_company_auto = True

    ticket_id = fields.Many2one(
        'sn.wsd.exception.ticket',
        string='Exception Ticket',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(related='ticket_id.company_id', store=True, index=True)
    started_at = fields.Datetime(string='Started At', required=True, default=fields.Datetime.now)
    ended_at = fields.Datetime(string='Ended At')
    reason = fields.Selection(PAUSE_REASON_SELECTION, string='Suspension Reason', required=True)
    duration_minutes = fields.Float(compute='_compute_duration_minutes', string='Duration (minutes)')

    @api.depends('started_at', 'ended_at')
    def _compute_duration_minutes(self):
        now = fields.Datetime.now()
        for pause in self:
            end = pause.ended_at or now
            pause.duration_minutes = (end - pause.started_at).total_seconds() / 60.0 if pause.started_at else 0.0

    @api.constrains('started_at', 'ended_at')
    def _check_period(self):
        for pause in self:
            if pause.ended_at and pause.started_at and pause.ended_at < pause.started_at:
                raise ValidationError(_('The suspension end cannot be earlier than its start.'))
