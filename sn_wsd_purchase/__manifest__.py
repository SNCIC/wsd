{
    'name': 'SN WSD Purchase Contract Report',
    'version': '19.0.3.4.0',
    'summary': 'Purchase contract fields, purchase detail tracking and vendor price sync',
    'depends': ['purchase', 'purchase_request', 'account', 'stock', 'sn_wsd_mrp', 'sn_wsd_material'],
    'data': [
        'data/purchase_contract_data.xml',
        'views/purchase_order_views.xml',
        'views/purchase_detail_views.xml',
        'report/purchase_contract_templates.xml',
        'report/purchase_contract_default_templates.xml',
        'report/purchase_contract_reports.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
