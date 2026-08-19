{
    'name': 'SN WSD Tooling',
    'version': '19.0.3.1.0',
    'summary': 'Tooling template, issue, maintenance, and usage management',
    'depends': ['mrp', 'stock', 'mail', 'sn_wsd_mrp', 'sn_wsd_device'],
    'data': [
        'security/tooling_security.xml',
        'security/ir.model.access.csv',
        'views/tooling_views.xml',
        'wizard/tooling_maintenance_wizard_views.xml',
        'wizard/tooling_pda_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
