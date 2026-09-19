{
    'name': 'SN WSD Stock Report',
    'version': '19.0.1.2.0',
    'summary': 'Stock in/out balance report by product and quant valuation aggregation',
    'category': 'Inventory/Inventory',
    'depends': ['stock', 'stock_account', 'sn_wsd_material'],
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
