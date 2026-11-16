{
    'name': 'WSD Injection Outsourcing',
    'summary': '整单代加工（委外）管理：代工厂档案、外发决策与询价比价、代工单、发料与模具外借、'
               '进度跟踪与交期预警、回货检验入库、物料平衡与对账结算、代工厂绩效',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'depends': ['sn_wsd_injection', 'purchase', 'purchase_stock', 'sale', 'mrp', 'stock', 'sn_wsd_api'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/cron_data.xml',
        'views/factory_views.xml',
        'views/request_views.xml',
        'views/order_views.xml',
        'views/issue_views.xml',
        'views/mold_loan_views.xml',
        'views/receipt_views.xml',
        'views/balance_views.xml',
        'views/statement_views.xml',
        'views/kpi_views.xml',
        'views/inherit_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_outsource/static/src/kpi/*',
        ],
    },
    'installable': True,
    'application': True,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
