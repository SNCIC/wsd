{
    'name': 'SN WSD Label Center',
    'version': '19.0.1.0.0',
    'summary': 'Designable label templates with ZPL / CPCL-JSON rendering',
    'category': 'Manufacturing/Manufacturing',
    'depends': ['mail'],
    'data': [
        'security/label_security.xml',
        'security/ir.model.access.csv',
        'security/label_rules.xml',
        'views/label_template_views.xml',
        'views/label_print_wizard_views.xml',
        'views/label_print_log_views.xml',
        'views/label_pda_views.xml',
        'report/label_print_reports.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
    'assets': {
        'web.assets_backend': [
            'sn_wsd_label/static/src/**/*.js',
            'sn_wsd_label/static/src/**/*.scss',
            'sn_wsd_label/static/src/**/*.xml',
        ],
    },
}
