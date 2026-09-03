{
    'name': 'WSD Pick to Light',
    'summary': 'Pick-to-light integration for smart shelves and warehouse devices',
    'description': """
This module integrates Odoo warehouse picking with smart shelf and pick-to-light
services. It records outbound commands, device callbacks, and sensor readings.
    """,
    'category': 'Inventory/Warehouse',
    'version': '19.0.1.0.0',
    'depends': ['stock', 'sn_wsd_barcode', 'sn_wsd_device'],
    'data': [
        'data/sequence.xml',
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/picklight_views.xml',
        'views/stock_picking_type_views.xml',
        'views/stock_picking_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
