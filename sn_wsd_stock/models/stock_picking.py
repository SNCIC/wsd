from odoo import models


class StockPicking(models.Model):
    """Keep the delivery address editable, and say so when it changes late.

    The address of a transfer (``partner_id``: delivery address on a delivery,
    receive-from on a receipt, contact on an internal transfer) is opened up
    in every state, so an address forgotten before validation can still be
    corrected. A change made on a done or cancelled transfer is posted on the
    chatter: the document no longer matches what was signed, delivered or
    invoiced, and the note keeps that visible.
    """

    _inherit = 'stock.picking'

    def write(self, vals):
        if 'partner_id' not in vals or self.env.context.get(
                'sn_skip_picking_partner_audit'):
            return super().write(vals)
        late = self.filtered(lambda picking: picking.state in ('done', 'cancel'))
        previous = {picking.id: picking.partner_id.display_name for picking in late}
        result = super().write(vals)
        for picking in late:
            new_name = picking.partner_id.display_name or self.env._('None')
            if previous[picking.id] != new_name:
                picking.message_post(body=self.env._(
                    'Contact changed after validation by %(user)s: '
                    '%(old)s -> %(new)s',
                    user=self.env.user.display_name,
                    old=previous[picking.id] or self.env._('None'),
                    new=new_name,
                ))
        return result
