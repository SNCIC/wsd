{
    'name': 'SN WSD Report',
    'version': '19.0.4.0.0',
    'summary': 'Reporting extensions for SN WSD manufacturing',
    'depends': ['sn_wsd_api', 'sn_wsd_quality', 'sn_wsd_device', 'stock', 'sale', 'mrp'],
    'data': [
        'security/ir.model.access.csv',
        'views/menu_views.xml',
    ],
    'assets': {
        # 3D 看板专用 bundle：three.js 单文件包，只在打开仓库 3D 运输看板时加载
        'sn_wsd_report.assets_warehouse_3d': [
            'sn_wsd_report/static/src/js/warehouse_3d_scene.bundle.js',
        ],
        # 整机自动线 3D 看板专用 bundle，同样按需加载
        'sn_wsd_report.assets_assembly_line_3d': [
            'sn_wsd_report/static/src/js/assembly_line_3d_scene.bundle.js',
        ],
        'web.assets_backend': [
            ('include', 'web.chartjs_lib'),
            'sn_wsd_report/static/src/js/mes_big_screen_action.js',
            'sn_wsd_report/static/src/xml/mes_big_screen_action.xml',
            'sn_wsd_report/static/src/scss/mes_big_screen_action.scss',
            'sn_wsd_report/static/src/js/warehouse_screen_action.js',
            'sn_wsd_report/static/src/xml/warehouse_screen_action.xml',
            'sn_wsd_report/static/src/scss/warehouse_screen_action.scss',
            'sn_wsd_report/static/src/js/ai_screen_action.js',
            'sn_wsd_report/static/src/xml/ai_screen_action.xml',
            'sn_wsd_report/static/src/scss/ai_screen_action.scss',
            'sn_wsd_report/static/src/js/order_flow_screen_action.js',
            'sn_wsd_report/static/src/xml/order_flow_screen_action.xml',
            'sn_wsd_report/static/src/scss/order_flow_screen_action.scss',
            'sn_wsd_report/static/src/js/workshop_screen_action.js',
            'sn_wsd_report/static/src/xml/workshop_screen_action.xml',
            'sn_wsd_report/static/src/scss/workshop_screen_action.scss',
            'sn_wsd_report/static/src/js/warehouse_3d_screen_action.js',
            'sn_wsd_report/static/src/xml/warehouse_3d_screen_action.xml',
            'sn_wsd_report/static/src/scss/warehouse_3d_screen_action.scss',
            'sn_wsd_report/static/src/js/assembly_line_3d_screen_action.js',
            'sn_wsd_report/static/src/xml/assembly_line_3d_screen_action.xml',
            'sn_wsd_report/static/src/scss/assembly_line_3d_screen_action.scss',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
