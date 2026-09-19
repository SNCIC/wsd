{
    'name': 'SN WSD Stock Report',
    'version': '19.0.1.1.0',
    'summary': 'Stock in/out balance report by product',
    'category': 'Inventory/Inventory',
    'depends': ['stock', 'sn_wsd_material'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_balance_report_views.xml',
        'views/stock_balance_wizard_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
