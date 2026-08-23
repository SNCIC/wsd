{
    'name': 'SN WSD Skip Station',
    'version': '19.0.3.2.0',
    'summary': 'Skip station requests for WSD meter manufacturing routes',
    'depends': ['mail', 'sn_wsd_wip'],
    'data': [
        'security/skip_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'views/skip_request_views.xml',
        'views/mrp_production_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
