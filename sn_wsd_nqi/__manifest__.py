{
    'name': "NQI Platform Integration",
    'summary': "NQI platform supplier data staging and push (data model V2.1)",
    'category': 'Manufacturing/MES',
    'version': '19.0.1.0.0',
    'depends': ['sn_wsd_mrp', 'sn_wsd_api', 'sn_wsd_device', 'hr'],
    'data': [
        'security/nqi_security.xml',
        'security/ir.model.access.csv',
        'views/nqi_menus.xml',
        'views/nqi_config_views.xml',
    ],
    'installable': True,
    'application': True,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
