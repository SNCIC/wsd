{
    'name': 'SN WSD Purchase Contract Report',
    'version': '19.0.1.0.0',
    'summary': 'Purchase contract fields and a printable purchase contract report',
    'depends': ['purchase', 'account', 'sn_wsd_mrp'],
    'data': [
        'data/purchase_contract_data.xml',
        'views/purchase_order_views.xml',
        'report/purchase_contract_templates.xml',
        'report/purchase_contract_default_templates.xml',
        'report/purchase_contract_reports.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
