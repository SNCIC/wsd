{
    'name': 'SN WSD 计件+计时（报工工时）',
    'version': '19.0.1.0.0',
    'summary': '每次报工同时记录件数和工时：工位终端开工/暂停/继续/完工计时、日报工填时段或工时、'
               '多人按在岗时段或比例记工时；计件单价扩展计酬方式（计件/计时）；工时分析（实际 vs 标准、'
               '小时产出、人均效率、单位人工成本）；月度计件计时汇总与 Excel 导出。只继承，不改既有文件。',
    'category': 'Manufacturing',
    'depends': ['sn_wsd_piece_rate', 'sn_wsd_workorder', 'sn_wsd_exception', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'views/time_entry_views.xml',
        'views/timer_views.xml',
        'views/analysis_views.xml',
        'views/payroll_views.xml',
        'views/inherit_views.xml',
        'views/menu_views.xml',
        'data/post_labels.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_piece_time/static/src/shop_floor_timer.js',
            'sn_wsd_piece_time/static/src/shop_floor_timer.xml',
            'sn_wsd_piece_time/static/src/workbench_time.xml',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
