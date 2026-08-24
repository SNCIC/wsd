{
    'name': 'SN WSD Shop Floor Terminal',
    'version': '19.0.2.6.0',
    'summary': 'Shop floor station terminal for WSD MES orders',
    'category': 'Manufacturing',
    'depends': ['sn_wsd_mrp', 'barcodes', 'sn_wsd_device', 'sn_wsd_exception', 'sn_wsd_quality'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'views/mrp_workcenter_views.xml',
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
