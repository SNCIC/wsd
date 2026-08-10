from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


class BomApplySubstituteWizard(models.TransientModel):
    _name = 'sn.wsd.bom.apply.substitute.wizard'
    _description = 'Apply BoM Substitute Wizard'

    bom_id = fields.Many2one(
        'mrp.bom',
        string='BoM',
        required=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='bom_id.company_id',
        readonly=True,
    )
    bom_line_id = fields.Many2one(
        'mrp.bom.line',
        string='Original BoM Line',
        required=True,
        readonly=True,
    )
    original_product_id = fields.Many2one(
        'product.product',
        string='Original Component',
        required=True,
        readonly=True,
    )
    original_qty = fields.Float(
        string='Available Qty',
        digits='Product Unit',
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Original UoM',
        required=True,
        readonly=True,
    )
    available_substitute_ids = fields.Many2many(
        'product.product',
        compute='_compute_available_substitute_ids',
    )
    substitute_product_id = fields.Many2one(
        'product.product',
        string='Substitute Component',
        required=True,
        domain="[('id', 'in', available_substitute_ids)]",
    )
    substitute_qty = fields.Float(
        string='Substitute Qty',
        digits='Product Unit',
        required=True,
    )
    substitute_product_uom_id = fields.Many2one(
        'uom.uom',
        string='Substitute UoM',
        related='substitute_product_id.uom_id',
        readonly=True,
    )
    operation_id = fields.Many2one(
        'mrp.routing.workcenter',
        string='Consumed in Operation',
        check_company=True,
        domain="[('bom_id', '=', bom_id)]",
    )
    substitution_mode = fields.Selection(
        [
            ('partial', 'Partial'),
            ('full', 'Full'),
        ],
        string='Mode',
        compute='_compute_substitution_mode',
    )

    @api.depends('original_product_id')
    def _compute_available_substitute_ids(self):
        for wizard in self:
            wizard.available_substitute_ids = wizard.original_product_id.substitute_ids

    @api.depends('substitute_qty', 'original_qty', 'product_uom_id')
    def _compute_substitution_mode(self):
        for wizard in self:
            if wizard.product_uom_id and float_compare(
                wizard.substitute_qty,
                wizard.original_qty,
                precision_rounding=wizard.product_uom_id.rounding,
            ) >= 0:
                wizard.substitution_mode = 'full'
            else:
                wizard.substitution_mode = 'partial'

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        line = self.env['mrp.bom.line'].browse(values.get('bom_line_id') or self.env.context.get('default_bom_line_id'))
        if line:
            values.setdefault('bom_id', line.bom_id.id)
            values.setdefault('original_product_id', line.product_id.id)
            values.setdefault('original_qty', line.product_qty)
            values.setdefault('product_uom_id', line.product_uom_id.id)
            values.setdefault('operation_id', line.operation_id.id)
        return values

    @api.constrains('bom_id', 'bom_line_id', 'original_product_id')
    def _check_context(self):
        for wizard in self:
            if wizard.bom_id.x_bom_stage_type != 'production':
                raise ValidationError(_('Substitutes can only be applied on production BoMs.'))
            if wizard.bom_line_id.bom_id != wizard.bom_id:
                raise ValidationError(_('The selected BoM line does not belong to the selected BoM.'))
            if wizard.bom_line_id.product_id != wizard.original_product_id:
                raise ValidationError(_('The original component must match the selected BoM line.'))

    @api.constrains('substitute_product_id', 'substitute_qty')
    def _check_substitute_values(self):
        for wizard in self:
            if wizard.substitute_product_id and wizard.substitute_product_id not in wizard.available_substitute_ids:
                raise ValidationError(_('The selected product is not configured as an allowed substitute.'))
            if wizard.substitute_product_id and wizard.product_uom_id:
                substitute_uom = wizard.substitute_product_id.uom_id
                original_uom = wizard.product_uom_id
                if substitute_uom and original_uom and not original_uom._has_common_reference(substitute_uom):
                    raise ValidationError(_('The substitute unit of measure must be in the same category as the original component unit.'))
            if wizard.product_uom_id and float_compare(
                wizard.substitute_qty,
                0.0,
                precision_rounding=wizard.product_uom_id.rounding,
            ) <= 0:
                raise ValidationError(_('The substitute quantity must be positive.'))
            if wizard.product_uom_id and float_compare(
                wizard.substitute_qty,
                wizard.original_qty,
                precision_rounding=wizard.product_uom_id.rounding,
            ) > 0:
                raise ValidationError(_('The substitute quantity cannot exceed the original component quantity.'))

    def _get_substitute_line_values(self, substitute_line_qty):
        self.ensure_one()
        return {
            'bom_id': self.bom_id.id,
            'product_id': self.substitute_product_id.id,
            'product_qty': substitute_line_qty,
            'product_uom_id': self.substitute_product_uom_id.id,
            'sequence': self.bom_line_id.sequence + 1,
            'operation_id': self.operation_id.id,
            'bom_product_template_attribute_value_ids': [
                fields.Command.set(self.bom_line_id.bom_product_template_attribute_value_ids.ids)
            ],
            'x_requires_feeder_verification': self.bom_line_id.x_requires_feeder_verification,
            'x_substitution_role': 'substitute',
            'x_substitution_origin_line_id': self.bom_line_id.id,
            'x_substitution_original_product_id': self.original_product_id.id,
            'x_substitution_substitute_product_id': self.substitute_product_id.id,
            'x_substitution_qty': self.substitute_qty,
        }

    def action_apply(self):
        self.ensure_one()
        if self.bom_id.x_plm_state in ('released', 'obsolete'):
            raise UserError(_('Released or obsolete production BoMs cannot be changed directly. Create a new revision instead.'))
        if self.bom_line_id.x_substitution_role == 'substitute':
            raise UserError(_('Apply substitutes on the original component line, not on a substitute line.'))

        remaining_qty = self.bom_line_id.product_qty - self.substitute_qty
        if float_compare(remaining_qty, 0.0, precision_rounding=self.product_uom_id.rounding) < 0:
            raise UserError(_('The substitute quantity cannot exceed the current original line quantity.'))

        substitute_line_qty = self.product_uom_id._compute_quantity(
            self.substitute_qty,
            self.substitute_product_uom_id,
            rounding_method='HALF-UP',
        )
        existing_line = self.bom_id.bom_line_ids.filtered(
            lambda line: line.x_substitution_origin_line_id == self.bom_line_id
            and line.product_id == self.substitute_product_id
            and line.product_uom_id == self.substitute_product_uom_id
            and line.operation_id == self.operation_id
        )[:1]

        if existing_line:
            existing_line.write({
                'product_qty': existing_line.product_qty + substitute_line_qty,
                'x_substitution_qty': existing_line.x_substitution_qty + self.substitute_qty,
            })
        else:
            self.env['mrp.bom.line'].create(self._get_substitute_line_values(substitute_line_qty))

        self.bom_line_id.write({
            'product_qty': 0.0 if float_is_zero(remaining_qty, precision_rounding=self.product_uom_id.rounding) else remaining_qty,
            'x_substitution_role': 'original',
            'x_substitution_substitute_product_id': self.substitute_product_id.id,
            'x_substitution_qty': self.bom_line_id.x_substitution_qty + self.substitute_qty,
        })
        return {'type': 'ir.actions.act_window_close'}
