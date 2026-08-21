{
    'name': 'SN WSD Tooling',
    'version': '19.0.4.0.0',
    'summary': 'Tooling types, templates, tooling lifecycle, and PDA service',
    'depends': ['mrp', 'stock', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/tooling_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
