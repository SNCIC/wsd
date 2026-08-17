from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MesPickWizard(models.TransientModel):
    """Material picking dialog (领料弹窗): how many finished units to issue
    with this batch (架构设计 3.3 ``qty_this``). Defaults to whatever remains
    of the MES order quantity; batches accumulate up to that quantity.
    """
    _name = 'sn.wsd.mes.pick.wizard'
    _description = 'MES Material Picking Wizard'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True,
    )
    name = fields.Char(related='mes_order_id.name')
    production_id = fields.Many2one(
        'mrp.production', related='mes_order_id.production_id',
    )
    planned_qty = fields.Float(related='mes_order_id.planned_qty')
    picked_qty = fields.Float(related='mes_order_id.picked_qty')
    remaining_qty = fields.Float(
        string='Remaining Quantity', compute='_compute_remaining_qty',
    )
    qty_this = fields.Float(string='Quantity To Pick', required=True)

    @api.depends('mes_order_id')
    def _compute_remaining_qty(self):
        for wizard in self:
            wizard.remaining_qty = (
                wizard.mes_order_id.planned_qty - wizard.mes_order_id.picked_qty)

    @api.onchange('mes_order_id')
    def _onchange_mes_order_id(self):
        if self.mes_order_id:
            self.qty_this = (
                self.mes_order_id.planned_qty - self.mes_order_id.picked_qty)

    def action_pick(self):
        self.ensure_one()
        order = self.mes_order_id
        if order.state != 'released':
            raise UserError(_(
                'Only Released MES orders can pick material (current: %s).',
                order.state))
        if self.qty_this <= 0 or self.qty_this != int(self.qty_this):
            raise ValidationError(
                _('The picked quantity must be a positive whole number of units.'))
        if self.qty_this + order.picked_qty > order.planned_qty + 0.0001:
            raise ValidationError(_(
                'Over-picking: only %(remaining)s unit(s) remain on %(order)s.',
                remaining=order.planned_qty - order.picked_qty, order=order.name))
        order.action_generate_picking(qty_this=self.qty_this)
        return {'type': 'ir.actions.act_window_close'}
