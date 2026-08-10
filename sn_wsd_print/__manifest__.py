{
    'name': 'SN WSD Print',
    'version': '19.0.1.1.0',
    'summary': 'ZPL printing for WSD internal serial labels',
    'depends': ['sn_wsd_mrp'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/internal_serial_generate_print_wizard_views.xml',
        'report/internal_serial_label_templates.xml',
        'report/internal_serial_label_reports.xml',
        'views/internal_serial_views.xml',
        'views/manufacturing_batch_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
