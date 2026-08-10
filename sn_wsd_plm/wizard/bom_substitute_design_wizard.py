from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command


class BomSubstituteDesignWizard(models.TransientModel):
    _name = 'sn.wsd.bom.substitute.design.wizard'
    _description = 'BoM Substitute Design Wizard'

    bom_id = fields.Many2one(
        'mrp.bom',
        string='BoM',
        required=True,
        readonly=True,
    )
    bom_line_id = fields.Many2one(
        'mrp.bom.line',
        string='BoM Line',
        required=True,
        readonly=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Component',
        required=True,
        readonly=True,
    )
    substitute_ids = fields.Many2many(
        'product.product',
        'sn_wsd_bom_substitute_design_wizard_product_rel',
        'wizard_id',
        'product_id',
        string='Allowed Substitutes',
        domain="[('id', '!=', product_id), ('type', '!=', 'service')]",
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        line = self.env['mrp.bom.line'].browse(values.get('bom_line_id') or self.env.context.get('default_bom_line_id'))
        if line:
            values.setdefault('bom_id', line.bom_id.id)
            values.setdefault('product_id', line.product_id.id)
            values['substitute_ids'] = [Command.set(line.product_id.substitute_ids.ids)]
        return values

    @api.constrains('bom_id', 'bom_line_id', 'product_id')
    def _check_context(self):
        for wizard in self:
            if wizard.bom_id.x_bom_stage_type != 'engineering':
                raise ValidationError(_('Substitute design is only available on engineering BoMs.'))
            if wizard.bom_line_id.bom_id != wizard.bom_id:
                raise ValidationError(_('The selected BoM line does not belong to the selected BoM.'))
            if wizard.bom_line_id.product_id != wizard.product_id:
                raise ValidationError(_('The component must match the selected BoM line.'))

    def action_apply(self):
        self.ensure_one()
        if self.bom_id.x_plm_state in ('released', 'obsolete'):
            raise UserError(_('Released or obsolete engineering BoMs cannot be changed directly. Create a new revision instead.'))
        if self.product_id in self.substitute_ids:
            raise UserError(_('A component cannot substitute itself.'))
        invalid_company = self.substitute_ids.filtered(
            lambda product: product.company_id and self.product_id.company_id and product.company_id != self.product_id.company_id
        )
        if invalid_company:
            raise UserError(_('Substitute products must belong to the same company as the component.'))
        self.product_id.write({'substitute_ids': [Command.set(self.substitute_ids.ids)]})
        return {'type': 'ir.actions.act_window_close'}
