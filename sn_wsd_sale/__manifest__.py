{
    'name': 'SN WSD Sale',
    'version': '19.0.1.10.0',
    'summary': 'Sales order detail, dot-matrix order sheet and customer-only customer field',
    'category': 'Sales/Sales',
    'depends': [
        'sale',
        'sn_wsd_material',
        'sn_wsd_list',
    ],
    'data': [
        'views/sale_order_views.xml',
        'views/sale_detail_views.xml',
        'report/sale_order_prn_templates.xml',
        'report/sale_order_prn_reports.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
