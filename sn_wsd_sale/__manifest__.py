{
    'name': 'SN WSD Sale',
    'version': '19.0.1.2.0',
    'summary': 'Sales order detail report',
    'category': 'Sales/Sales',
    'depends': [
        'sale',
        'sn_wsd_material',
        'sn_wsd_list',
    ],
    'data': [
        'views/sale_order_views.xml',
        'views/sale_detail_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
