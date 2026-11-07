{
    'name': 'SN WSD Sale',
    'version': '19.0.1.11.0',
    'summary': 'Sales order detail, dot-matrix order sheet and customer-only customer field',
    'category': 'Sales/Sales',
    'depends': [
        'sale',
        'sale_stock',
        'sn_wsd_material',
        'sn_wsd_list',
        'sn_wsd_prn',
    ],
    'data': [
        # The report templates and actions come first: the sale order views below
        # reference action_report_sale_order_prn, which report/sale_order_prn_reports.xml
        # creates, and that file in turn needs the QWeb template of the report.
        'report/sale_order_prn_templates.xml',
        'report/sale_order_prn_reports.xml',
        'views/sale_order_views.xml',
        'views/sale_detail_views.xml',
        'views/stock_picking_prn_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
