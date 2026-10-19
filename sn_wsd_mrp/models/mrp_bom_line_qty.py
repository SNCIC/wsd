from fractions import Fraction

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# The ERP expresses the component usage as numerator / denominator. In the live
# Kingdee account every denominator is an integer (up to 20000) while the
# numerator may be a decimal (0.00089, 0.05, 0.12, ...), so the numerator is a
# float and the denominator an integer.
MAX_FRACTION_DENOMINATOR = 20000


def fraction_from_qty(qty):
    """Return ``(numerator, denominator)`` for a component quantity.

    Only used when the quantity comes from a source that has no fraction
    (catalog, copies, scripts). The value stored by the ERP is rounded, so the
    closest fraction is a best effort, not the original numerator/denominator.
    """
    fraction = Fraction(float(qty or 0.0)).limit_denominator(
        MAX_FRACTION_DENOMINATOR)
    return float(fraction.numerator), fraction.denominator


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    product_code = fields.Char(
        string='Component Code',
        related='product_id.default_code',
        store=True,
        index=True,
        readonly=True,
    )
    qty_numerator = fields.Float(
        string='Numerator',
        default=1.0,
        digits=(16, 6),
        help='The component quantity is the numerator divided by the '
             'denominator, as in the ERP bill of materials.',
    )
    qty_denominator = fields.Integer(
        string='Denominator',
        default=1,
        help='The component quantity is the numerator divided by the '
             'denominator, as in the ERP bill of materials.',
    )

    _qty_denominator_not_zero = models.Constraint(
        'CHECK (qty_denominator <> 0)',
        'The denominator of the component quantity must not be zero.',
    )

    @api.model
    def _qty_from_fraction(self, numerator, denominator):
        if not denominator:
            raise ValidationError(
                _('The denominator of the component quantity must not be zero.'))
        return numerator / denominator

    @api.onchange('qty_numerator', 'qty_denominator')
    def _onchange_qty_fraction(self):
        for line in self:
            if line.qty_denominator:
                line.product_qty = line.qty_numerator / line.qty_denominator

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'qty_numerator' in vals or 'qty_denominator' in vals:
                # The fraction is the source of truth: the ERP expresses the
                # component usage as numerator / denominator.
                vals['product_qty'] = self._qty_from_fraction(
                    vals.get('qty_numerator', 1.0),
                    vals.get('qty_denominator', 1))
            elif 'product_qty' in vals:
                # Catalog, import, scripts and copies only provide the
                # quantity; keep the fraction readable and consistent.
                vals['qty_numerator'], vals['qty_denominator'] = fraction_from_qty(
                    vals['product_qty'])
        return super().create(vals_list)

    def write(self, vals):
        qty_fields = {'product_qty', 'qty_numerator', 'qty_denominator'}
        if not qty_fields.intersection(vals):
            return super().write(vals)
        if 'qty_numerator' not in vals and 'qty_denominator' not in vals:
            # Only the quantity changed: write() is called by the catalog, the
            # ECO rebase and external scripts, so the fraction must follow.
            numerator, denominator = fraction_from_qty(vals['product_qty'])
            return super().write(dict(
                vals, qty_numerator=numerator, qty_denominator=denominator))
        if len(self) == 1:
            numerator = vals.get('qty_numerator', self.qty_numerator)
            denominator = vals.get('qty_denominator', self.qty_denominator)
            return super().write(dict(
                vals,
                qty_numerator=numerator,
                qty_denominator=denominator,
                product_qty=self._qty_from_fraction(numerator, denominator),
            ))
        result = True
        for line in self:
            numerator = vals.get('qty_numerator', line.qty_numerator)
            denominator = vals.get('qty_denominator', line.qty_denominator)
            line_vals = dict(
                vals,
                qty_numerator=numerator,
                qty_denominator=denominator,
                product_qty=self._qty_from_fraction(numerator, denominator),
            )
            result = super(MrpBomLine, line).write(line_vals) and result
        return result
