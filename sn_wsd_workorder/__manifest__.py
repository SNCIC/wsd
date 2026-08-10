{
    'name': 'SN WSD Shop Floor Work Orders',
    'version': '19.0.1.0.0',
    'summary': 'Shop floor execution panel for WSD manufacturing work orders',
    'category': 'Manufacturing',
    'depends': ['sn_wsd_mrp', 'sn_wsd_report', 'barcodes', 'hr_hourly_cost'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'views/mrp_workcenter_views.xml',
        'views/mrp_workorder_views.xml',
        'views/mrp_production_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_workorder/static/src/scss/shop_floor.scss',
            'sn_wsd_workorder/static/src/js/shop_floor.js',
            'sn_wsd_workorder/static/src/xml/shop_floor.xml',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
