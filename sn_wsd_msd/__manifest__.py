{
    'name': 'SN WSD MSD',
    'version': '19.0.1.0.0',
    'summary': 'MSD material control for electric meter manufacturing',
    'depends': ['stock', 'mrp', 'sn_wsd_mrp', 'sn_wsd_smt'],
    'data': [
        'security/ir.model.access.csv',
        'views/msd_level_views.xml',
        'views/msd_control_rule_views.xml',
        'views/product_views.xml',
        'views/stock_lot_views.xml',
        'wizard/msd_bake_wizard_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
