{
    'name': 'SN WSD Tooling',
    'version': '19.0.4.2.0',
    'summary': 'Tooling types, templates, tooling lifecycle, and PDA service',
    'depends': ['mrp', 'stock', 'mail', 'sn_wsd_smt', 'sn_wsd_code_rule'],
    'data': [
        'security/ir.model.access.csv',
        'views/tooling_views.xml',
        'data/code_rule_seeds.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
