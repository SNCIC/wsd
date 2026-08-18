{
    'name': 'SN WSD Scrap',
    'version': '19.0.3.2.0',
    'summary': 'Scrap record management for SN-based manufacturing',
    'depends': ['mrp', 'stock', 'mail', 'sn_wsd_mrp', 'sn_wsd_quality', 'sn_wsd_report'],
    'data': [
        'data/ir_sequence.xml',
        'security/ir.model.access.csv',
        'views/sn_wsd_scrap_views.xml',
        'views/mrp_production_views.xml',
        'views/meter_quality_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
