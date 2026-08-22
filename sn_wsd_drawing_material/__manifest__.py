{
    'name': 'SN WSD Drawing Material Relations',
    'summary': 'Drawing-number material lists (tooling / consumable / material) per workshop, operation and side',
    'version': '19.0.2.1.0',
    'depends': ['sn_wsd_mrp', 'sn_wsd_tooling', 'sn_wsd_consumable'],
    'data': [
        'security/ir.model.access.csv',
        'views/drawing_material_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
