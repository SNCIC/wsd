from odoo import fields, models


class ProductTemplate(models.Model):
    """A product may only use a category of its own company (or a shared one).

    ``product.template`` already runs ``_check_company_auto``; declaring
    ``check_company`` on the category makes that check cover the tree as well.
    """

    _inherit = 'product.template'

    categ_id = fields.Many2one(
        comodel_name='product.category',
        string='Product Category',
        group_expand='_read_group_categ_id',
        tracking=True,
        check_company=True,
    )
