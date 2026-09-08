{
    'name': 'SN WSD Code Rule',
    'version': '19.0.1.0.0',
    'summary': 'Configurable document coding rules for the manufacturing domain',
    'category': 'Manufacturing/Manufacturing',
    'depends': ['stock', 'sn_wsd_field'],
    'data': [
        'security/ir.model.access.csv',
        'views/code_rule_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
