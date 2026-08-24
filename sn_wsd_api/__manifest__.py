{
    'name': 'SN WSD API',
    'version': '19.0.5.3.0',
    'summary': 'MES device test-result ingestion (legacy flows removed; API rewrite planned)',
    'depends': ['sn_wsd_mrp', 'sn_wsd_device', 'sn_wsd_smt', 'sn_wsd_tooling', 'sn_wsd_consumable'],
    'data': [
        'security/ir.model.access.csv',
        'views/api_request_log_views.xml',
        'views/api_data_tables.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_api/static/src/js/test_result_split.js',
            'sn_wsd_api/static/src/xml/test_result_split.xml',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
