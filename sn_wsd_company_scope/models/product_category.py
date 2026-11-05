from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductCategory(models.Model):
    """Give the category tree a company so two companies can keep separate trees.

    Odoo keeps ``product.category`` global on purpose, which means a database
    shared by several companies shows every company's categories to everybody.
    The field stays optional: a category without company is shared, the same
    convention the other master data models use.
    """

    _inherit = 'product.category'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        index=True,
        ondelete='restrict',
        default=lambda self: self._sn_default_company(),
        help='Leave empty to share the category with every company.',
    )

    @api.model
    def _sn_default_company(self):
        """Default a new category to its parent's company, else to the current one.

        Without a default a category created from the form would stay shared and
        show up in every company, which defeats the isolation exactly where a
        user creates data by hand.
        """
        parent = self.parent_id
        if parent:
            return parent.company_id
        return self.env.company

    @api.constrains('company_id', 'parent_id')
    def _check_company_matches_parent(self):
        for category in self:
            parent_company = category.parent_id.company_id
            if parent_company and category.company_id != parent_company:
                raise ValidationError(_(
                    'The category "%(child)s" must belong to the same company as '
                    'its parent "%(parent)s".',
                    child=category.display_name,
                    parent=category.parent_id.display_name,
                ))
            wrong_children = category.child_id.filtered(
                lambda child: child.company_id != category.company_id)
            if wrong_children:
                raise ValidationError(_(
                    'The category "%(parent)s" cannot belong to %(company)s '
                    'because its subcategories belong to another company: %(children)s',
                    parent=category.display_name,
                    company=category.company_id.display_name or _('every company'),
                    children=', '.join(wrong_children.mapped('display_name')),
                ))

    @api.model
    def _sn_get_company_tree(self):
        """Categories of the current company plus the shared ones."""
        return self.search([
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.env.company.id),
        ])
