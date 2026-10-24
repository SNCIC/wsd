{
    'name': 'SN WSD Other Stock Operations',
    'version': '19.0.1.0.4',
    'summary': 'Other receipts and deliveries moving the stock without a purchase or a sale',
    'category': 'Supply Chain/Inventory',
    'depends': ['stock'],
    'data': [
        'views/other_operation_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
