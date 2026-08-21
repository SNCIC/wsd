from odoo import fields, models


class SnSmtCartMountWizard(models.TransientModel):
    _name = 'sn.smt.cart.mount.wizard'
    _description = 'SMT Cart Mount Wizard'

    cart_id = fields.Many2one(
        'sn.smt.cart',
        string='CART_SN',
        required=True,
        check_company=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        required=True,
        check_company=True,
    )

    def action_confirm(self):
        self.ensure_one()
        self.cart_id.action_mount(self.workcenter_id)
        return {'type': 'ir.actions.act_window_close'}
