from odoo import fields, models, _
from odoo.exceptions import UserError


class StockLot(models.Model):
    """Quality hold state mirrored on the batch or serial number.

    The state is written by ``sn.wsd.stock.hold``: a held batch keeps its
    quantity and traceability but every outgoing flow refuses it until the hold
    is released.
    """

    _inherit = 'stock.lot'

    sn_hold_state = fields.Selection(
        selection=[
            ('none', 'Normal'),
            ('sealed', 'Sealed'),
            ('blocked', 'Blocked'),
        ],
        string='Quality Hold',
        default='none',
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )
    sn_hold_reason = fields.Text(
        string='Hold Reason', readonly=True, copy=False,
    )
    sn_hold_id = fields.Many2one(
        comodel_name='sn.wsd.stock.hold',
        string='Hold Document',
        readonly=True,
        copy=False,
        index=True,
    )
    sn_hold_date = fields.Datetime(
        string='Hold Date', readonly=True, copy=False,
    )

    def _sn_check_usable(self):
        """Refuse a held batch or serial number.

        Called by every flow that consumes stock: outgoing transfers,
        reservations, SMT loading and the quality flows.
        """
        for lot in self:
            if lot.sn_hold_state in (False, 'none'):
                continue
            label = dict(
                lot._fields['sn_hold_state'].selection
            ).get(lot.sn_hold_state, lot.sn_hold_state)
            raise UserError(_(
                'Batch/Serial %(lot)s is %(state)s and cannot be used. '
                'Hold %(hold)s: %(reason)s',
                lot=lot.name, state=label,
                hold=lot.sn_hold_id.name or '',
                reason=lot.sn_hold_reason or '',
            ))

    def action_sn_open_hold(self):
        """Open a quality hold form prefilled with this batch."""
        self.ensure_one()
        if self.sn_hold_state not in (False, 'none'):
            raise UserError(_('This batch is already held.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quality Hold'),
            'res_model': 'sn.wsd.stock.hold',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_target_type': 'lot',
                'default_hold_type': 'blocked',
                'default_product_id': self.product_id.id,
                'default_lot_id': self.id,
            },
        }

    def action_sn_release_hold(self):
        """Release the active hold of the selected batches."""
        holds = self.mapped('sn_hold_id').filtered(
            lambda hold: hold.state == 'active'
        )
        if not holds:
            raise UserError(_('The selected batches are not held.'))
        return holds.action_release()
