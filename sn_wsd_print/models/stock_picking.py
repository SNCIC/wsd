from odoo import _, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    can_print_material_labels = fields.Boolean(
        string='Can Print Material Labels',
        compute='_compute_can_print_material_labels',
    )

    def _compute_can_print_material_labels(self):
        for picking in self:
            picking.can_print_material_labels = (
                picking.picking_type_code == 'incoming'
                and picking.state not in ('done', 'cancel')
                and bool(picking.move_ids.filtered(
                    lambda move: move.product_id and move.product_id.tracking == 'lot'
                ))
            )

    def action_open_material_label_wizard(self):
        self.ensure_one()
        if not self.can_print_material_labels:
            raise UserError(_('Material labels can only be printed for active receipts.'))
        view = self.env.ref(
            'sn_wsd_print.view_incoming_material_label_wizard_form'
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate and Print Material Labels'),
            'res_model': 'sn.wsd.incoming.material.label.wizard',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
            'context': {'default_picking_id': self.id},
        }
