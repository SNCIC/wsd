from odoo import _, fields, models
from odoo.exceptions import UserError


class SnWsdExceptionCancelWizard(models.TransientModel):
    _name = 'sn.wsd.exception.cancel.wizard'
    _description = 'SN WSD Exception Cancel Wizard'

    ticket_id = fields.Many2one(
        'sn.wsd.exception.ticket',
        string='Exception Ticket',
        required=True,
        ondelete='cascade',
    )
    note = fields.Text(string='Cancellation Note', required=True)

    def action_confirm(self):
        for wizard in self:
            if not wizard.note.strip():
                raise UserError(_('A cancellation note is required.'))
            wizard.ticket_id.action_cancel(note=wizard.note)
        return {'type': 'ir.actions.act_window_close'}
