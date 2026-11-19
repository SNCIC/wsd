from odoo import models
from odoo.fields import Domain


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def _get_gather_domain(self, product_id, location_id, lot_id=None,
                           package_id=None, owner_id=None, strict=False):
        """Keep the goods owned by a customer out of the company reservations.

        The supplied material and the finished goods of a toll manufacturing
        order are stored in the same locations as our own stock, only the
        owner differs. The standard reservation ignores the owner when none is
        requested, which would let any delivery or manufacturing order consume
        the customer goods. Restricting the candidate quants to the ownerless
        ones and to the company-owned ones makes the separation effective
        while the explicit owner of a toll transfer still reaches its goods.
        """
        domain = super()._get_gather_domain(
            product_id, location_id, lot_id, package_id, owner_id, strict)
        if owner_id or strict:
            return domain
        if self.env.context.get('sn_toll_allow_customer_owned'):
            return domain
        company = location_id.company_id or self.env.company
        return domain & Domain(
            'owner_id', 'in', [False, company.partner_id.id])
