{
    'name': 'SN WSD Stock',
    'version': '19.0.1.2.2',
    'summary': 'Incoming material labels and internal lot generation',
    'category': 'Supply Chain/Inventory',
    'depends': ['stock', 'mail', 'resource', 'sn_wsd_mrp'],
    'data': [
        'data/ir_sequence.xml',
        'report/incoming_material_label_templates.xml',
        'report/incoming_material_label_reports.xml',
        'views/stock_lot_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_rule_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_stock/static/src/js/refresh_current_view_action.js',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
