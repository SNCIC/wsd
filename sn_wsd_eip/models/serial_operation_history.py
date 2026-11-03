from odoo import models


class SerialOperationHistoryEip(models.Model):
    """Capture hook: the verdict backfill is the single convergence
    point of every pass channel (device API, terminal, PDA, batch pass,
    OQC rework) -- the EIP collection row is born here, inside the pass
    transaction."""
    _inherit = 'sn.wsd.serial.operation.history'

    def write(self, vals):
        # only an in_progress -> ok/ng transition is a completed
        # inspection (scrap is not a test verdict and is not collected)
        transitioning = (
            self.filtered(lambda row: row.result == 'in_progress')
            if vals.get('result') in ('ok', 'ng')
            else self.env['sn.wsd.serial.operation.history'])
        res = super().write(vals)
        if transitioning:
            self.env['sn.wsd.eip.pass.record'].sudo()._capture_from_history(
                transitioning)
        return res
