{
    'name': 'SN WSD Partner',
    'version': '19.0.1.0.0',
    'summary': 'Supplier group codes and automatically generated supplier references',
    'category': 'Purchase/Purchase',
    'depends': ['sn_wsd_code_rule'],
    'data': [
        'data/supplier_code_data.xml',
        'views/res_partner_category_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
