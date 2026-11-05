from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    supplier_categ_id = fields.Many2one(
        'sn.wsd.supplier.group', string='Supplier Group', copy=False,
        index=True, ondelete='restrict',
        help='Group the contact is a supplier of. Its code prefixes the '
             'supplier code generated when the reference is left empty.')

    @api.model_create_multi
    def create(self, vals_list):
        self._assign_supplier_codes(vals_list)
        return super().create(vals_list)

    @api.model
    def _assign_supplier_codes(self, vals_list):
        """Fill the reference of the contacts created with a supplier group.

        An explicitly given reference always wins — the same contract the
        coding rule engine applies to document names — and a contact without a
        supplier group is left untouched, so customers and hand-numbered
        records keep their reference."""
        Rule = self.env['sn.code.rule']
        Seed = self.env['sn.supplier.code.seed']
        for vals in vals_list:
            if vals.get('ref') or not vals.get('supplier_categ_id'):
                continue
            candidate = self.new(vals)
            rule = Rule._find_rule(candidate)
            if not rule:
                continue
            Seed._seed_supplier_counter(rule, candidate)
            vals['ref'] = rule.render(candidate)
