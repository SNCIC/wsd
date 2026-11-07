from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    """A company-owned product must not use another company's category.

    ``check_company`` on ``categ_id`` would look right, but Odoo refuses a
    *shared* record (no company) that points at a company-owned one: the check
    domain becomes ``[('company_id', '=', False)]``, so every product without a
    company fails as soon as it carries a company category. Legacy databases are
    full of such rows, so the rule is expressed as a constraint instead: it only
    fires when both sides carry a company and the two differ.
    """

    _inherit = 'product.template'

    categ_id = fields.Many2one(
        comodel_name='product.category',
        string='Product Category',
        group_expand='_read_group_categ_id',
        tracking=True,
    )

    @api.constrains('categ_id', 'company_id')
    def _check_categ_company(self):
        for product in self:
            categ_company = product.categ_id.company_id
            if product.company_id and categ_company and product.company_id != categ_company:
                raise ValidationError(_(
                    'The product "%(product)s" belongs to %(company)s while its category '
                    '"%(categ)s" belongs to %(categ_company)s.',
                    product=product.display_name,
                    company=product.company_id.display_name,
                    categ=product.categ_id.display_name,
                    categ_company=categ_company.display_name,
                ))
