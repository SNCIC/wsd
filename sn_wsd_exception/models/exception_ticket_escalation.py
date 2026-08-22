from odoo import fields, models


class SnWsdExceptionTicketEscalation(models.Model):
    _name = 'sn.wsd.exception.ticket.escalation'
    _description = 'SN WSD Exception Ticket Escalation Log'
    _order = 'ticket_id, escalated_at, id'
    _check_company_auto = True

    ticket_id = fields.Many2one(
        'sn.wsd.exception.ticket',
        string='Exception Ticket',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(related='ticket_id.company_id', store=True, index=True)
    escalated_at = fields.Datetime(string='Escalated At', required=True, default=fields.Datetime.now)
    stage = fields.Integer(string='Escalation Stage', required=True)
    user_id = fields.Many2one('res.users', string='Notified User', index=True)
