{
    'name': 'SN WSD Partner',
    'version': '19.0.4.2.0',
    'summary': 'Supplier groups, automatically generated supplier references '
               'and rights on the vendor finance data',
    'category': 'Purchase/Purchase',
    'depends': ['sn_wsd_code_rule', 'contacts', 'purchase', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'security/supplier_finance_security.xml',
        'data/supplier_code_data.xml',
        'views/supplier_group_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
