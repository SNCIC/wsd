{
    'name': 'SN WSD Consumable Control',
    'version': '19.0.3.2.0',
    'summary': 'SMT auxiliary material lifecycle control',
    'depends': ['sn_wsd_mrp', 'stock', 'sn_wsd_smt', 'sn_wsd_code_rule'],
    'data': [
        'security/ir.model.access.csv',
        'views/sn_consumable_views.xml',
        'data/code_rule_seeds.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
