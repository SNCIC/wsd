from odoo import _, api, models
from odoo.exceptions import UserError


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    def _sn_check_supplier_bank_rights(self, partners):
        """Raise when a vendor bank account is written by an unauthorised user.

        The bank account of a vendor is the account the money is paid to, so
        adding or changing it is restricted to the finance editors. Calls made
        in superuser mode (imports, synchronisation) stay allowed.
        """
        if self.env.su or self.env.context.get('sn_skip_supplier_finance_check'):
            return
        if self.env.user.has_group('sn_wsd_partner.group_supplier_finance_editor'):
            return
        vendors = partners.filtered(
            lambda partner: partner.supplier_rank > 0
            or partner.commercial_partner_id.supplier_rank > 0)
        if vendors:
            raise UserError(_(
                "You are not allowed to change the bank accounts of a vendor. "
                "Ask a purchase manager or an accountant."))

    def _sn_supplier_bank_partners(self, vals_list):
        partner_ids = {vals.get('partner_id') for vals in vals_list if vals.get('partner_id')}
        return self.env['res.partner'].browse(partner_ids)

    @api.model_create_multi
    def create(self, vals_list):
        self._sn_check_supplier_bank_rights(self._sn_supplier_bank_partners(vals_list))
        return super().create(vals_list)

    def write(self, vals):
        partners = self.partner_id
        if vals.get('partner_id'):
            partners |= self.env['res.partner'].browse(vals['partner_id'])
        self._sn_check_supplier_bank_rights(partners)
        return super().write(vals)

    def unlink(self):
        self._sn_check_supplier_bank_rights(self.partner_id)
        return super().unlink()
