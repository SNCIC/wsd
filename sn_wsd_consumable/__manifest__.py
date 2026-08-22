{
    'name': 'SN WSD Consumable Control',
    'version': '19.0.3.1.0',
    'summary': 'SMT auxiliary material lifecycle control',
    'depends': ['sn_wsd_mrp', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/sn_consumable_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
