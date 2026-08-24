# -*- coding: utf-8 -*-

{
    'name': "WSD Barcode",
    'summary': "Use barcode scanners to process logistics operations",
    'description': """
This module enables the barcode scanning feature for the warehouse management system.
    """,
    'category': 'Supply Chain/Inventory',
    'sequence': 255,
    'version': '19.0.2.0.0',
    'depends': ['stock', 'web_tour', 'sn_wsd_api', 'sn_wsd_smt',
                 'sn_wsd_quality', 'sn_wsd_tooling', 'sn_wsd_consumable'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_inventory_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_picking_type_views.xml',
        'views/stock_move_line_views.xml',
        'views/sn_wsd_barcode_views.xml',
        'views/barcode_pda_views.xml',
        'views/res_config_settings_views.xml',
        'views/stock_scrap_views.xml',
        'views/stock_location_views.xml',
        'wizard/sn_wsd_barcode_cancel_operation.xml',
        'wizard/stock_backorder_confirmation_views.xml',
        'data/data.xml',
    ],
    'demo': [
        'data/demo.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
    'author': 'WSD',
    'license': 'LGPL-3',
    'assets': {
        'web.assets_backend': [
            'sn_wsd_barcode/static/src/**/*.js',
            'sn_wsd_barcode/static/src/**/*.scss',
            'sn_wsd_barcode/static/src/**/*.xml',

            # Don't include dark mode files in light mode
            ('remove', 'sn_wsd_barcode/static/src/**/*.dark.scss'),
        ],
        "web.assets_web_dark": [
            'sn_wsd_barcode/static/src/**/*.dark.scss',
        ],
    }
}
