{
    'name': 'SN WSD Purchase Contract Report',
    'version': '19.0.3.7.0',
    'summary': 'Purchase contract fields, purchase detail tracking and vendor price sync',
    'depends': ['purchase', 'purchase_request', 'account', 'stock', 'sn_wsd_mrp', 'sn_wsd_material', 'sn_wsd_code_rule'],
    'data': [
        'data/purchase_contract_data.xml',
        'data/purchase_request_code_rule.xml',
        'views/purchase_order_views.xml',
        'views/purchase_detail_views.xml',
        'report/purchase_contract_templates.xml',
        'report/purchase_contract_default_templates.xml',
        'report/purchase_contract_reports.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_purchase/static/src/list/merged_cells_list.js',
            'sn_wsd_purchase/static/src/list/merged_cells_list.scss',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
