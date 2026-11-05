{
    'name': 'SN WSD BOM',
    'version': '19.0.1.3.0',
    'summary': 'BOM Excel import, flat BOM detail list and line batch update',
    'description': 'Import tree-structured ERP BOM Excel exports into mrp.bom through a '
                   'wizard, and browse every BOM component line in a flat list where the '
                   'parent columns are printed once per BOM.',
    'depends': ['mrp', 'sn_wsd_mrp', 'sn_wsd_material', 'sn_wsd_plm'],
    'data': [
        'security/ir.model.access.csv',
        'views/bom_import_views.xml',
        'views/mrp_bom_detail_views.xml',
        'report/mrp_report_bom_structure.xml',
        'wizard/bom_line_batch_update_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_bom/static/src/components/**/*.js',
            'sn_wsd_bom/static/src/components/**/*.xml',
            'sn_wsd_bom/static/src/list/bom_merged_cells_list.js',
            'sn_wsd_bom/static/src/list/bom_merged_cells_list.scss',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
