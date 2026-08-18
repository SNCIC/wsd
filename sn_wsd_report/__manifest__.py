{
    'name': 'SN WSD Report',
    'version': '19.0.3.1.1',
    'summary': 'Reporting extensions for SN WSD manufacturing',
    'depends': ['sn_wsd_api', 'sn_wsd_quality'],
    'data': [
        'security/ir.model.access.csv',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            ('include', 'web.chartjs_lib'),
            'sn_wsd_report/static/src/js/mes_big_screen_action.js',
            'sn_wsd_report/static/src/xml/mes_big_screen_action.xml',
            'sn_wsd_report/static/src/scss/mes_big_screen_action.scss',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
