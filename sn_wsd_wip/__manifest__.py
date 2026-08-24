{
    'name': 'SN WSD WIP',
    'version': '19.0.3.1.1',
    'summary': 'WIP reporting and visualization for manufacturing orders',
    'depends': ['mrp', 'sn_wsd_api', 'sn_wsd_quality'],
    'data': [
        'security/ir.model.access.csv',
        'views/wip_report_views.xml',
        'views/mrp_production_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
