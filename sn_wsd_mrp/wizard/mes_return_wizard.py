from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MesReturnWizard(models.TransientModel):
    """Material return dialog (退料弹窗): how many finished units' worth of
    components to send back to the warehouse. The generated reverse picking
    carries a NEGATIVE ``x_mes_order_qty`` so the net picked ledger stays
    truthful (mes-picking-lifecycle R2)."""
    _name = 'sn.wsd.mes.return.wizard'
    _description = 'MES Material Return Wizard'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True,
    )
    name = fields.Char(related='mes_order_id.name')
    production_id = fields.Many2one(
        'mrp.production', related='mes_order_id.production_id',
    )
    planned_qty = fields.Float(related='mes_order_id.planned_qty')
    picked_qty = fields.Float(related='mes_order_id.picked_qty')
    qty_return = fields.Float(string='Quantity To Return', required=True)

    @api.onchange('mes_order_id')
    def _onchange_mes_order_id(self):
        if self.mes_order_id:
            self.qty_return = self.mes_order_id.picked_qty

    def action_return(self):
        self.ensure_one()
        order = self.mes_order_id
        if order.state == 'cancelled':
            raise UserError(
                _('A cancelled MES order cannot return material.'))
        if self.qty_return <= 0 or self.qty_return != int(self.qty_return):
            raise ValidationError(
                _('The returned quantity must be a positive whole number of units.'))
        if self.qty_return > order.picked_qty + 0.0001:
            raise ValidationError(_(
                'Over-return: only %(net)s unit(s) were net picked on %(order)s.',
                net=order.picked_qty, order=order.name))
        order.action_generate_return(qty=self.qty_return)
        return {'type': 'ir.actions.act_window_close'}
