from odoo import fields, models, _
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    """Material level quality hold.

    A material disabled for quality reasons cannot be purchased nor used until
    the hold is released; the batches already in stock keep their own hold
    state, so disabling a material does not rewrite their history.
    """

    _inherit = 'product.template'

    sn_hold_state = fields.Selection(
        selection=[
            ('none', 'Normal'),
            ('disabled', 'Disabled'),
        ],
        string='Quality Hold',
        default='none',
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )
    sn_hold_reason = fields.Text(
        string='Hold Reason', readonly=True, copy=False,
    )
    sn_hold_id = fields.Many2one(
        comodel_name='sn.wsd.stock.hold',
        string='Hold Document',
        readonly=True,
        copy=False,
        index=True,
    )
    sn_hold_date = fields.Datetime(
        string='Hold Date', readonly=True, copy=False,
    )

    def _sn_check_usable(self):
        for template in self:
            if template.sn_hold_state != 'disabled':
                continue
            raise UserError(_(
                'Material %(product)s is disabled for quality reasons and '
                'cannot be used. Hold %(hold)s: %(reason)s',
                product=template.display_name,
                hold=template.sn_hold_id.name or '',
                reason=template.sn_hold_reason or '',
            ))

    def action_sn_open_hold(self):
        """Open a quality hold form prefilled with this material."""
        self.ensure_one()
        if self.sn_hold_state == 'disabled':
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
                'default_product_id': self.product_variant_id.id,
            },
        }

    def action_sn_release_hold(self):
        holds = self.mapped('sn_hold_id').filtered(
            lambda hold: hold.state == 'active'
        )
        if not holds:
            raise UserError(_('The selected materials are not held.'))
        return holds.action_release()
