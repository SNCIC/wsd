from odoo import fields, models

from ..models.exception_ticket import PAUSE_REASON_SELECTION


class SnWsdExceptionSuspendWizard(models.TransientModel):
    _name = 'sn.wsd.exception.suspend.wizard'
    _description = 'SN WSD Exception Suspend Wizard'

    ticket_id = fields.Many2one(
        'sn.wsd.exception.ticket',
        string='Exception Ticket',
        required=True,
        ondelete='cascade',
    )
    reason = fields.Selection(
        PAUSE_REASON_SELECTION,
        string='Suspension Reason',
        required=True,
        default='spare_part',
    )

    def action_confirm(self):
        for wizard in self:
            wizard.ticket_id.action_suspend(wizard.reason)
        return {'type': 'ir.actions.act_window_close'}
