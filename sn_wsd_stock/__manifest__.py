{
    'name': 'SN WSD Stock',
    'version': '19.0.1.4.0',
    'summary': 'Incoming material labels and internal lot generation',
    'category': 'Supply Chain/Inventory',
    'depends': ['stock', 'mail', 'resource', 'sn_wsd_mrp', 'sn_wsd_label'],
    'data': [
        'data/ir_sequence.xml',
        'data/label_template_incoming.xml',
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
