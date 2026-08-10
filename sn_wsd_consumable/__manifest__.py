{
    'name': 'SN WSD Consumable Control',
    'version': '19.0.1.0.0',
    'summary': 'Consumable control for electric meter manufacturing',
    'depends': ['mrp', 'product', 'mail','sn_wsd_mrp'],
    'data': [
        'security/ir.model.access.csv',
        'views/sn_consumable_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
