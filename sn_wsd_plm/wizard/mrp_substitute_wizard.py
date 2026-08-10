from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MrpSubstituteWizard(models.TransientModel):
    _inherit = 'mrp.substitute.wizard'

    @api.depends('production_id.bom_id.bom_line_ids.product_id.substitute_ids')
    def _compute_available_bom_line_ids(self):
        for wizard in self:
            bom = wizard.production_id.bom_id
            wizard.available_bom_line_ids = bom.bom_line_ids.filtered(lambda line: line.product_id.substitute_ids) if bom else False

    def action_validate(self):
        self.ensure_one()
        if not self.scanned_product_id:
            raise UserError(_('The scanned substitute product could not be identified.'))
        if not self.bom_line_id:
            raise UserError(_('No substitute-enabled BoM line exists for the selected original product on this manufacturing order.'))
        if self.scanned_product_id not in self.original_product_id.substitute_ids:
            raise UserError(_(
                '%(sub)s cannot replace %(org)s. Configure the substitute on the product first.',
                sub=self.scanned_product_id.display_name,
                org=self.original_product_id.display_name,
            ))

        substitute_bom_line = self.production_id.bom_id.bom_line_ids.filtered(
            lambda line: line.product_id == self.scanned_product_id
            and line.x_substitution_origin_line_id == self.bom_line_id
        )[:1]
        if not substitute_bom_line:
            raise UserError(_(
                'The substitute product is not present on the manufacturing order. Update the production BoM and regenerate the order before recording usage.'
            ))

        usage = self.env['mrp.substitute.usage'].create({
            'production_id': self.production_id.id,
            'workorder_id': self.workorder_id.id,
            'bom_id': self.production_id.bom_id.id,
            'bom_line_id': self.bom_line_id.id,
            'substitute_bom_line_id': substitute_bom_line.id,
            'original_product_id': self.original_product_id.id,
            'substitute_product_id': self.scanned_product_id.id,
            'substitute_lot_id': self.substitute_lot_id.id,
            'original_uom_qty': self.substitute_qty,
            'substitute_uom_qty': self.substitute_qty,
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now(),
            'state': 'approved',
            'note': self.note,
        })

        return {
            'type': 'ir.actions.act_window_close',
            'infos': {'usage_id': usage.id},
        }
