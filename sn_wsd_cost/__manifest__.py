{
    'name': 'SN WSD Cost',
    'version': '19.0.1.0.2',
    'summary': 'Latest purchase price of the materials and BoM cost computed from it',
    'description': 'Store the latest confirmed purchase price of every material with the '
                   'purchase date and vendor, and compute the BoM cost from those prices '
                   'instead of the standard cost. The BoM lines, the BoM overview screen '
                   'and its PDF export show the unit price and the purchase date next to '
                   'every component.',
    'depends': ['purchase', 'mrp', 'sn_wsd_purchase'],
    'data': [
        'data/ir_cron.xml',
        'views/product_views.xml',
        'views/mrp_bom_views.xml',
        'report/mrp_report_bom_structure.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_cost/static/src/components/**/*.js',
            'sn_wsd_cost/static/src/components/**/*.xml',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
