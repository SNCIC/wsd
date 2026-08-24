{
    'name': 'SN WSD API',
    'version': '19.0.4.0.0',
    'summary': 'MES device test-result ingestion (legacy flows removed; API rewrite planned)',
    'depends': ['sn_wsd_mrp', 'sn_wsd_device', 'sn_wsd_smt', 'sn_wsd_tooling'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
