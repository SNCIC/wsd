{
    'name': 'SN WSD Contract',
    'version': '19.0.1.1.0',
    'summary': 'Contract templates and the sales contract report',
    'category': 'Sales/Sales',
    'depends': [
        'sale',
        'sn_wsd_sale',
        'sn_wsd_material',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/contract_template_data.xml',
        'report/sale_contract_reports.xml',
        'report/sale_contract_templates.xml',
        'views/contract_template_views.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
