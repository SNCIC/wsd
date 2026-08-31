from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    reel_split_id = fields.Many2one(
        'sn.lot.reel.split',
        string='Reel Split',
        copy=False,
        readonly=True,
        index=True,
        ondelete='restrict',
    )
    reel_split_role = fields.Selection(
        [('consume', 'Consume Source Lot'), ('produce', 'Produce Reel Lot')],
        string='Reel Split Role',
        copy=False,
        readonly=True,
    )


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _prepare_new_lot_vals(self):
        vals = super()._prepare_new_lot_vals()
        if self.picking_code == 'incoming':
            vals['arrival_batch_no'] = fields.Date.context_today(self).strftime('%Y%m%d')
        return vals
