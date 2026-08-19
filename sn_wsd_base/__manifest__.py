# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'SN WSD Base',
    'version': '19.0.1.0.0',
    'summary': 'Hierarchical search panels for product and stock master data',
    'category': 'Inventory/Inventory',
    'depends': ['product', 'stock', 'sale'],
    'data': [
        'views/hierarchical_list_views.xml',
        'views/product_action_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
