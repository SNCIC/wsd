{
    'name': 'SN WSD API',
    'version': '19.0.5.6.0',
    'summary': 'MES device test-result ingestion (legacy flows removed; API rewrite planned)',
    'depends': ['sn_wsd_mrp', 'sn_wsd_device', 'sn_wsd_smt', 'sn_wsd_tooling', 'sn_wsd_consumable'],
    'data': [
        'security/ir.model.access.csv',
        'views/api_request_log_views.xml',
        'views/api_data_tables.xml',
        'views/sn_trace_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_api/static/src/js/test_result_split.js',
            'sn_wsd_api/static/src/xml/test_result_split.xml',
            'sn_wsd_api/static/src/js/trace_page.js',
            'sn_wsd_api/static/src/xml/trace_page.xml',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
