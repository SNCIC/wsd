from odoo import _, models
from odoo.exceptions import UserError


class ProductProduct(models.Model):
    """Expose the quality hold actions on the variant form as well.

    The product form is shared by the template and its variants: the buttons on
    it are called on ``product.product`` when the record opened is a variant,
    and the delegation that gives the variant the template fields does not
    proxy the template methods.
    """

    _inherit = 'product.product'

    def action_sn_open_hold(self):
        """Open a quality hold form prefilled with this variant."""
        self.ensure_one()
        if self.product_tmpl_id.sn_hold_state == 'disabled':
            raise UserError(_('This material is already disabled.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quality Hold'),
            'res_model': 'sn.wsd.stock.hold',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_target_type': 'product',
                'default_hold_type': 'disabled',
                'default_product_id': self.id,
            },
        }

    def action_sn_release_hold(self):
        """Release the active hold of the material of this variant."""
        self.ensure_one()
        return self.product_tmpl_id.action_sn_release_hold()
