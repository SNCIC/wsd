{
    'name': 'SN WSD Repair',
    'version': '19.0.3.1.4',
    'summary': 'Production repair management for SN and quantity reporting',
    'depends': ['mrp', 'stock', 'mail', 'sn_wsd_api', 'sn_wsd_scrap', 'sn_wsd_quality', 'sn_wsd_report'],
    'data': [
        'data/ir_sequence.xml',
        'security/ir.model.access.csv',
        'views/sn_wsd_repair_views.xml',
        'views/mrp_production_views.xml',
        'views/mrp_workorder_views.xml',
        'views/meter_quality_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
