{
    'name': 'WSD Injection Molding MES',
    'summary': '注塑车间核心功能：模具台账（复用工装）、注塑机（复用设备台账）、标准工艺卡、'
               '逐模次参数采集与 SPC、换模单（SMED）、注塑排产（甘特）、原料烘干、配色配方、'
               '水口料回用管控、按模次报工、注塑车间看板',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'depends': [
        'mail', 'hr', 'mrp', 'stock',
        'sn_wsd_tooling', 'sn_wsd_device', 'sn_wsd_mrp', 'sn_wsd_exception',
        'sn_wsd_gantt', 'sn_wsd_api',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/master_data.xml',
        'data/cron_data.xml',
        'views/mold_views.xml',
        'views/machine_views.xml',
        'views/process_card_views.xml',
        'views/plan_views.xml',
        'views/shot_views.xml',
        'views/mold_change_views.xml',
        'views/material_views.xml',
        'views/color_views.xml',
        'views/regrind_views.xml',
        'views/report_views.xml',
        'views/board_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_injection/static/src/board/*',
            'sn_wsd_injection/static/src/spc/*',
        ],
    },
    'installable': True,
    'application': True,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
