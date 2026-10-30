from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OqcReworkWizard(models.TransientModel):
    """One-step rework decision on an OQC inspection (oqc-ng-disposition):
    pick the NG board, the operation it goes back to, and why. The board
    re-walks its route from there and must re-pass the inspection
    operation; no document is created besides the chatter note."""

    _name = 'sn.wsd.quality.oqc.rework.wizard'
    _description = 'OQC Rework Decision'

    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection', required=True, ondelete='cascade')
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN', required=True,
        domain="[('id', 'in', serial_ids)]",
        help='NG sample board pulled back through rework.')
    serial_ids = fields.Many2many(
        'sn.wsd.serial.identity', string='Pickable Serials',
        compute='_compute_serial_ids')
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Rework Operation',
        required=True,
        domain="[('id', 'in', route_operation_ids)]",
        help='Operation the board goes back to; it re-walks the route '
             'from there on its original MES order (no material picking).')
    route_operation_ids = fields.Many2many(
        'sn.wsd.mes.order.route.operation', string='Route Operations',
        compute='_compute_route_operations')
    reason = fields.Text(required=True)

    @api.depends('inspection_id')
    def _compute_serial_ids(self):
        for wizard in self:
            inspection = wizard.inspection_id
            ng = inspection.x_oqc_ng_serial_ids | inspection.cell_ids\
                .filtered(lambda c: c.result == 'fail')\
                .mapped('serial_identity_id')
            wizard.serial_ids = inspection.x_fai_serial_ids & ng

    @api.depends('inspection_id')
    def _compute_route_operations(self):
        for wizard in self:
            wizard.route_operation_ids = (
                wizard.inspection_id.mes_order_id.x_mes_route_id.operation_ids)

    def action_apply(self):
        self.ensure_one()
        self.inspection_id.action_rework_sn(
            self.serial_identity_id, self.route_operation_id, self.reason)
        return {'type': 'ir.actions.act_window_close'}
