from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class OqcFullCloseWizard(models.TransientModel):
    """Full-lot quantity-gap closure (oqc-disposition-closure task 3.3).

    The full-lot ledger counts inspected boards one by one at the station;
    when fewer boards than the lot were inspected the inspection may still
    close — but only with an explicit confirmation and a non-empty closure
    reason, recorded as a batch full_close event. The confirmation covers
    the quantity gap only: known open dispositions still refuse the
    closure inside action_done."""

    _name = 'sn.wsd.quality.oqc.full.close.wizard'
    _description = 'OQC Full-Lot Quantity Gap Closure'

    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection', required=True, ondelete='cascade')
    inspected_qty = fields.Integer(
        string='Inspected Boards', readonly=True,
        help='Boards with a finished pass at the inspection operation, '
             'counted per serial number (repeated retests do not count).')
    lot_qty = fields.Integer(string='Lot Quantity', readonly=True)
    gap_qty = fields.Integer(string='Gap', compute='_compute_gap_qty')
    reason = fields.Text(
        string='Closure Reason', required=True,
        help='Why the lot closes with fewer inspected boards than planned.')

    @api.depends('inspected_qty', 'lot_qty')
    def _compute_gap_qty(self):
        for wizard in self:
            wizard.gap_qty = max(
                (wizard.lot_qty or 0) - (wizard.inspected_qty or 0), 0)

    @api.onchange('inspection_id')
    def _onchange_inspection_ledger(self):
        inspection = self.inspection_id
        if not inspection:
            return
        self.inspected_qty = len(inspection._oqc_full_inspected_serials())
        self.lot_qty = int(inspection.lot_qty or 0)

    def action_apply(self):
        self.ensure_one()
        inspection = self.inspection_id
        reason = (self.reason or '').strip()
        if not reason:
            raise ValidationError(_(
                'State why the full-lot inspection closes with a gap.'))
        if not inspection.x_full_inspection:
            raise UserError(_(
                'The quantity-gap closure applies to full-lot inspections '
                'only.'))
        inspected = len(inspection._oqc_full_inspected_serials())
        lot_qty = int(inspection.lot_qty or 0)
        if inspected >= lot_qty:
            raise UserError(_(
                'Every board of the lot has been inspected: close the '
                'inspection normally, no gap confirmation is needed.'))
        if (self.inspected_qty or 0) != inspected:
            raise UserError(_(
                'The inspected count changed since the dialog opened '
                '(%(old)s -> %(new)s): review the boards and confirm '
                'again.', old=self.inspected_qty, new=inspected))
        inspection._oqc_lock()
        inspection.with_context(
            sn_wsd_oqc_full_close_reason=reason).action_done()
        return {'type': 'ir.actions.act_window_close'}
