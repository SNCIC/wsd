{
    'name': 'SN WSD Purchase Contract Report',
    'version': '19.0.3.0.1',
    'summary': 'Purchase contract fields and purchase detail tracking',
    'depends': ['purchase', 'purchase_request', 'account', 'sn_wsd_mrp', 'sn_wsd_material'],
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
