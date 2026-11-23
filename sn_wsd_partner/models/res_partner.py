from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    supplier_categ_id = fields.Many2one(
        'sn.wsd.supplier.group', string='Supplier Group', copy=False,
        index=True, ondelete='restrict',
        help='Group the contact is a supplier of. Its code prefixes the '
             'supplier code generated when the reference is left empty.')

    sn_can_edit_supplier_finance = fields.Boolean(
        string='Can Edit Supplier Finance',
        compute='_compute_sn_can_edit_supplier_finance',
        help='Technical field telling the form whether the user may change the '
             'vendor payment terms and the vendor bank accounts.')

    @api.depends_context('uid')
    def _compute_sn_can_edit_supplier_finance(self):
        allowed = self.env.user.has_group(
            'sn_wsd_partner.group_supplier_finance_editor')
        for partner in self:
            partner.sn_can_edit_supplier_finance = allowed

    def _sn_check_supplier_finance_rights(self):
        """Raise when the user may not edit the finance data of a supplier."""
        if self.env.su or self.env.context.get('sn_skip_supplier_finance_check'):
            return
        if self.env.user.has_group('sn_wsd_partner.group_supplier_finance_editor'):
            return
        raise UserError(_(
            "You are not allowed to change the payment terms or the bank "
            "accounts of a vendor. Ask a purchase manager or an accountant."))

    def write(self, vals):
        if 'property_supplier_payment_term_id' in vals and not (
            self.env.su
            or self.env.context.get('sn_skip_supplier_finance_check')
            or self.env.user.has_group('sn_wsd_partner.group_supplier_finance_editor')
        ):
            new_term_id = vals['property_supplier_payment_term_id'] or False
            changed = any(
                partner.property_supplier_payment_term_id.id != new_term_id
                for partner in self)
            if changed:
                self._sn_check_supplier_finance_rights()
        return super().write(vals)

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
