{
    'name': 'SN WSD Partner',
    'version': '19.0.4.0.0',
    'summary': 'Supplier groups and automatically generated supplier references',
    'category': 'Purchase/Purchase',
    'depends': ['sn_wsd_code_rule', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'data/supplier_code_data.xml',
        'views/supplier_group_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
