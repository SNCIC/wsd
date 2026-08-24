{
    'name': 'SN WSD Quality',
    'version': '19.0.4.0.2',
    'summary': 'Quality management for WSD meter manufacturing',
    'depends': ['sn_wsd_api', 'mail'],
    'data': [
        'data/ir_sequence.xml',
        'security/ir.model.access.csv',
        'views/sampling_views.xml',
        'views/meter_component_trace_views.xml',
        'views/meter_quality_views.xml',
        'views/serial_freeze_views.xml',
        'wizard/serial_freeze_wizard_views.xml',
        'views/quality_inspection_views.xml',
        'views/internal_serial_quality_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_quality/static/src/sampling_matrix/sampling_matrix.js',
            'sn_wsd_quality/static/src/sampling_matrix/sampling_matrix.xml',
            'sn_wsd_quality/static/src/sampling_matrix/sampling_matrix.scss',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
