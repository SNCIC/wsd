{
    'name': 'SN WSD Drawing Material Relations',
    'summary': 'Drawing-number material lists and ESOP work instructions',
    'version': '19.0.2.2.0',
    'depends': [
        'sn_wsd_mrp',
        'sn_wsd_tooling',
        'sn_wsd_consumable',
        'sn_wsd_workorder',
        'bus',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/drawing_material_views.xml',
        'views/menu_views.xml',
        'views/esop_views.xml',
        'views/esop_menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_drawing_material/static/src/scss/esop_screen.scss',
            'sn_wsd_drawing_material/static/src/js/esop_screen.js',
            'sn_wsd_drawing_material/static/src/js/shop_floor_esop_link.js',
            'sn_wsd_drawing_material/static/src/xml/esop_screen.xml',
            'sn_wsd_drawing_material/static/src/xml/shop_floor_esop_link.xml',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
