{
    'name': 'SN WSD BOM Excel Import',
    'version': '19.0.1.0.0',
    'summary': 'Import tree-structured ERP BOM Excel exports into mrp.bom through a wizard',
    'description': 'Upload a tree-structured ERP BOM template and import top-level '
                   'and sub-assembly BOMs bottom-up with workshop, UoM, and material validation plus duplicate skipping.',
    'depends': ['sn_wsd_mrp'],
    'data': [
        'security/ir.model.access.csv',
        'views/bom_import_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
