from odoo import api, models
from odoo.fields import Domain


class ProductProduct(models.Model):
    """Let the product lookup of the order lines match the material
    specification typed on the product: the salespeople know the specification
    of what they sell better than its internal reference.

    ``product.product.name_search`` is rewritten by the product module and does
    not go through ``_search_display_name``, so the specification matches are
    added to its results here.
    """

    _inherit = 'product.product'

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        results = super().name_search(name, domain, operator, limit)
        if not name or operator in Domain.NEGATIVE_OPERATORS:
            return results
        matched = self.search_fetch(
            Domain(domain or Domain.TRUE) & Domain('product_tmpl_id.material_specification', operator, name),
            ['display_name'],
            limit=limit,
        )
        known_ids = {result[0] for result in results}
        results += [
            (product.id, product.display_name)
            for product in matched.sudo()
            if product.id not in known_ids
        ]
        return results[:limit] if limit else results

    @api.depends('product_tmpl_id.material_specification')
    @api.depends_context('formatted_display_name')
    def _compute_display_name(self):
        super()._compute_display_name()
        if not self.env.context.get('formatted_display_name'):
            return
        for product in self:
            specification = product.product_tmpl_id.material_specification
            if specification and product.display_name:
                product.display_name = f'{product.display_name}\n\t{specification}'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if operator in Domain.NEGATIVE_OPERATORS or not value:
            return domain
        return Domain.OR([domain, [('material_specification', operator, value)]])

    @api.depends('material_specification')
    @api.depends_context('formatted_display_name')
    def _compute_display_name(self):
        super()._compute_display_name()
        if not self.env.context.get('formatted_display_name'):
            return
        for template in self:
            if template.material_specification and template.display_name:
                template.display_name = f'{template.display_name}\n\t{template.material_specification}'
