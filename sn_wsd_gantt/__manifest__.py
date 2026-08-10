{
    'name': 'SN WSD Gantt',
    'version': '19.0.1.0.0',
    'summary': 'Gantt view support for manufacturing schedules',
    'depends': ['web', 'mrp', 'sn_wsd_mrp'],
    'data': [
        'views/mrp_production_views.xml',
    ],
    'assets': {
        'web._assets_primary_variables': [
            'sn_wsd_gantt/static/src/gantt_view.variables.scss',
        ],
        'web.assets_backend_lazy': [
            'sn_wsd_gantt/static/src/**/*',
            ('remove', 'sn_wsd_gantt/static/src/**/*.dark.scss'),
        ],
        'web.assets_backend_lazy_dark': [
            'sn_wsd_gantt/static/src/**/*.dark.scss',
        ],
        'web.dark_mode_variables': [
            (
                'before',
                'sn_wsd_gantt/static/src/gantt_view.variables.scss',
                'sn_wsd_gantt/static/src/**/*.variables.dark.scss',
            ),
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
