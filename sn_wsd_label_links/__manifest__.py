{
    'name': 'SN WSD Label Links',
    'version': '19.0.1.0.0',
    'summary': 'Print-label entry points and seed templates for business models',
    'category': 'Manufacturing/Manufacturing',
    'depends': [
        'sn_wsd_label',
        'sn_wsd_tooling',
        'sn_wsd_consumable',
        'sn_wsd_device',
        'sn_wsd_mrp',
        'sn_wsd_barcode',
    ],
    'data': [
        'views/label_links_views.xml',
        'data/label_templates.xml',        'views/menu_moves.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
