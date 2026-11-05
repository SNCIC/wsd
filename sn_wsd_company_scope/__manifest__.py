{
    'name': 'SN WSD Company Scope',
    'version': '19.0.1.0.0',
    'summary': 'Company scoping for master data that Odoo keeps global',
    'description': """
Company scoping for master data that Odoo keeps global
======================================================

Odoo keeps several master data models global (no company field), so two
companies sharing one database have to share them as well. ``product.category``
is the most visible case: the category tree is global and every user sees every
company's categories.

This module adds a company on ``product.category`` and filters it per allowed
company, so each company only sees its own tree (plus the categories left
shared on purpose).

Behaviour
---------
* ``company_id`` on ``product.category`` (empty = shared by every company).
* A subcategory must belong to the same company as its parent.
* ``product.template.categ_id`` gains ``check_company``, so a product cannot be
  linked to a category of another company.
* A global record rule hides the categories of the other companies.

The categories that already exist are assigned to a company by the install
hook: everything under the domestic root goes to the first company, everything
under the second root goes to the second one.
""",
    'category': 'Inventory/Inventory',
    'depends': [
        'product',
    ],
    'data': [
        'security/company_scope_rules.xml',
        'views/product_category_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
