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
        'sn.wsd.serial.identity', string='SN',
        domain="[('id', 'in', serial_candidate_ids)]",
        help='NG sample board pulled back through rework.')
    serial_candidate_ids = fields.Many2many(
        'sn.wsd.serial.identity',
        'sn_wsd_quality_oqc_rework_wizard_serial_rel',
        'wizard_id', 'serial_id', string='Pickable Serials')
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Rework Operation',
        domain="[('id', 'in', route_operation_candidate_ids)]",
        help='Operation the board goes back to; it re-walks the route '
             'from there on its original MES order (no material picking).')
    route_operation_candidate_ids = fields.Many2many(
        'sn.wsd.mes.order.route.operation',
        'sn_wsd_quality_oqc_rework_wizard_route_rel',
        'wizard_id', 'route_operation_id', string='Pickable Operations')
    reason = fields.Text(required=True)

    @api.onchange('inspection_id')
    def _onchange_inspection_candidates(self):
        # onchange 里赋值随响应回传客户端，字段上的静态 domain 引用
        # 候选 m2m 即可求值（Odoo 17+ 不再支持 onchange 返回 domain）
        self.serial_candidate_ids = False
        self.route_operation_candidate_ids = False
        inspection = self.inspection_id
        if not inspection:
            return
        ng = inspection.x_oqc_ng_serial_ids | inspection.cell_ids\
            .filtered(lambda c: c.result == 'fail')\
            .mapped('serial_identity_id')
        self.serial_candidate_ids = inspection.x_fai_serial_ids & ng
        self.route_operation_candidate_ids = \
            inspection.mes_order_id.x_mes_route_id.operation_ids

    def action_apply(self):
        self.ensure_one()
        if not self.serial_identity_id:
            raise ValidationError(_('Pick the board to send back.'))
        if not self.route_operation_id:
            raise ValidationError(_('Pick the operation to send it back to.'))
        self.inspection_id.action_rework_sn(
            self.serial_identity_id, self.route_operation_id, self.reason)
        return {'type': 'ir.actions.act_window_close'}
