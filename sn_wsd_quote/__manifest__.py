{
    'name': 'SN WSD Quote',
    'version': '19.0.1.0.0',
    'summary': 'Quotation estimate: BoM material cost at the latest purchase prices, '
               'operation cost, expenses, margin and quantity tiers',
    'description': 'Independent quotation estimate worksheet. A quote is built from '
                   'the bill of materials of a product: the material lines carry the '
                   'latest purchase price and its purchase date, the operation lines '
                   'the piece rate or the work-center cost of the process route. The '
                   'worksheet adds the overhead, the management and the one-off costs, '
                   'applies the markup and prints the cost sheet used to quote the '
                   'customer.',
    'category': 'Sales/Sales',
    'depends': [
        'sale',
        'mrp',
        'sn_wsd_cost',
        'sn_wsd_mrp',
        'sn_wsd_material',
        'sn_wsd_piece_rate',
    ],
    'data': [
        'security/quote_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        # The report action comes before the form view: the form prints the
        # cost sheet through it.
        'report/quote_report_views.xml',
        'wizard/quote_generate_views.xml',
        'views/quote_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
