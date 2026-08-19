# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'SN WSD Product Lifecycle Management',
    'version': '19.0.1.0.0',
    'category': 'Supply Chain/Product Lifecycle Management (PLM)',
    'sequence': 155,
    'summary': 'Engineering change orders and bill of materials versioning',
    'depends': ['mrp'],
    'description': """
SN WSD Product Lifecycle Management
===================================

* Manage engineering change orders for products and bills of materials
* Track bill of materials and product versions
* Configure approval flows for engineering changes

""",
    'data': [
        'security/mrp_plm.xml',
        'security/ir.model.access.csv',
        'data/mrp_data.xml',
        'views/mrp_bom_views.xml',
        'views/mrp_document_views.xml',
        'views/mrp_eco_views.xml',
        'views/product_views.xml',
        'views/mrp_production_views.xml',
        'report/mrp_report_bom_structure.xml',
    ],
    'demo': ['data/mrp_demo.xml'],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
    'assets': {
        'web.assets_backend': [
            'sn_wsd_plm/static/src/**/*.js',
            'sn_wsd_plm/static/src/**/*.scss',
            'sn_wsd_plm/static/src/**/*.xml',
        ],
    },
}
