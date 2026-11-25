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

    # ------------------------------------------------------------------
    # Customer profile (filled by the Kingdee customer import)
    #
    # Odoo keeps a customer and a vendor in ``res.partner`` and has no field for
    # the invoicing data a Chinese sales account needs: the delivery code the
    # customer uses on its own papers, the delivery site, the invoice header and
    # the invoicing bank. They are declared here, close to the rest of the
    # partner data, so the sales, the delivery and the invoicing documents read
    # them; ``sn_wsd_kingdee`` fills them from BD_Customer.
    # ------------------------------------------------------------------
    sn_delivery_code = fields.Char(
        string='Delivery Code', copy=False, index=True,
        help='Code the customer uses to identify its delivery site (Kingdee '
             'F_QNBG_Text of BD_Customer). Printed on the delivery documents.')
    sn_delivery_address = fields.Char(
        string='Delivery Address', copy=False,
        help='Site the goods are sent to when it differs from the invoice '
             'address (Kingdee F_QNBG_Remark of BD_Customer).')
    sn_invoice_title = fields.Char(
        string='Invoice Title', copy=False,
        help='Name the customer asks on its invoices (Kingdee FINVOICETITLE). '
             'It often differs from the customer name, e.g. when the invoice '
             'goes to a group company or a project.')
    sn_invoice_phone = fields.Char(
        string='Invoice Phone', copy=False,
        help='Phone printed on the invoice (Kingdee FINVOICETEL).')
    sn_invoice_address = fields.Char(
        string='Invoice Address', copy=False,
        help='Address printed on the invoice (Kingdee FINVOICEADDRESS).')
    sn_invoice_bank_name = fields.Char(
        string='Invoice Bank', copy=False,
        help='Bank the customer asks on its invoices, as free text (Kingdee '
             'FINVOICEBANKNAME). The account number is stored as a bank account '
             'of the contact.')
    sn_rec_condition_number = fields.Char(
        string='Receivable Condition Code', copy=False, index=True,
        help='Number (FNumber) of the Kingdee receivable condition '
             '(BD_RecCondition) of this customer. Kept even when no Odoo '
             'payment term carries that number yet.')
    sn_rec_condition_name = fields.Char(
        string='Receivable Condition', copy=False, readonly=True,
        help='Name the account gives to the receivable condition above, so the '
             'screen shows the code and what it stands for.')
    sn_settlement_currency_id = fields.Many2one(
        'res.currency', string='Settlement Currency', copy=False,
        ondelete='restrict',
        help='Currency the account settles this customer in (Kingdee '
             'FTRADINGCURRID). The currency of the pricelist still drives the '
             'sale orders; this field keeps the account value.')

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
