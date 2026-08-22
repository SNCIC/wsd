from odoo import _, fields, models
from odoo.exceptions import UserError


class SnWsdExceptionRejectWizard(models.TransientModel):
    _name = 'sn.wsd.exception.reject.wizard'
    _description = 'SN WSD Exception Reject Wizard'

    ticket_id = fields.Many2one(
        'sn.wsd.exception.ticket',
        string='Exception Ticket',
        required=True,
        ondelete='cascade',
    )
    note = fields.Text(string='Rejection Note', required=True)

    def action_confirm(self):
        for wizard in self:
            if not wizard.note.strip():
                raise UserError(_('A rejection note is required.'))
            wizard.ticket_id.action_reject(wizard.note)
        return {'type': 'ir.actions.act_window_close'}
