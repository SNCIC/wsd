# -*- coding: utf-8 -*-
"""Completion wizard (完工入库向导) for MES orders."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MesDoneWizard(models.TransientModel):
    _name = 'sn.wsd.mes.done.wizard'
    _description = 'MES Order Completion Wizard'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='制令单', required=True, readonly=True,
    )
    output_qty = fields.Float(
        string='产出数量', related='mes_order_id.x_output_qty', readonly=True,
    )
    done_qty = fields.Float(
        string='已完工数量', related='mes_order_id.x_done_qty', readonly=True,
    )
    qty = fields.Float(string='本次完工数量', required=True)
    destination = fields.Selection(
        [('stock', '成品库（待仓库验证）'),
         ('lineside', '车间线边仓（直接验证）')],
        string='入库去向', required=True, default='stock',
    )
    workshop_id = fields.Many2one(
        'sn.mrp.workshop', string='入库车间',
        domain="[('component_location_id', '!=', False)]",
        help='Line-side workshop for the receipt destination. Only workshops '
             'of the order warehouse are offered.',
    )
    product_tracking = fields.Selection(
        related='mes_order_id.production_id.product_id.tracking',
        string='Product Tracking',
    )
    lot_name = fields.Char(
        string='Finished Goods Lot',
        help='Lot number stamped on the completion receipt lines. Leave '
             'empty to auto-generate one per MES order and day.',
    )
    available_workshop_ids = fields.Many2many(
        'sn.mrp.workshop', string='可选车间', compute='_compute_available_workshops',
    )

    def _order_warehouse(self):
        self.ensure_one()
        return self.mes_order_id.production_id.picking_type_id.warehouse_id

    @api.depends('mes_order_id')
    def _compute_available_workshops(self):
        Workshop = self.env['sn.mrp.workshop']
        for wizard in self:
            warehouse = wizard._order_warehouse()
            workshops = Workshop.search([
                ('component_location_id', '!=', False),
                ('company_id', '=', wizard.mes_order_id.company_id.id),
            ]).filtered(
                lambda ws: ws.component_location_id.warehouse_id == warehouse)
            wizard.available_workshop_ids = workshops

    @api.onchange('destination')
    def _onchange_destination(self):
        if self.destination != 'lineside' and self.workshop_id:
            self.workshop_id = False

    @api.constrains('qty', 'destination', 'workshop_id')
    def _check(self):
        for wizard in self:
            if wizard.qty <= 0:
                raise ValidationError(_('The completion quantity must be positive.'))
            if wizard.destination == 'lineside' and not wizard.workshop_id:
                raise ValidationError(_(
                    'Select a workshop for a line-side completion.'))

    def action_confirm(self):
        for wizard in self:
            wizard.mes_order_id.action_complete(
                wizard.qty, wizard.destination, workshop=wizard.workshop_id,
                lot_name=wizard.lot_name)
        return {'type': 'ir.actions.act_window_close'}
