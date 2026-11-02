{
    'name': "EIP Data Collection",
    'summary': "EIP (State Grid EIP) station-pass data collection staging",
    'category': 'Manufacturing/MES',
    'version': '19.0.1.0.0',
    'depends': ['sn_wsd_mrp', 'sn_wsd_api', 'sn_wsd_device', 'sn_wsd_workorder'],
    'data': [
        'security/ir.model.access.csv',
        'views/eip_operation_mapping_views.xml',
        'views/eip_value_mapping_views.xml',
        'data/cron_eip.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
