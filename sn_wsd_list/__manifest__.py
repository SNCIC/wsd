# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'SN WSD List',
    'version': '19.0.1.0.0',
    'summary': 'Per-column filters on list view headers',
    'category': 'Hidden',
    'depends': ['web'],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_list/static/src/xml/list_renderer_inherit.xml',
            'sn_wsd_list/static/src/js/column_filter_utils.js',
            'sn_wsd_list/static/src/js/search_model_patch.js',
            'sn_wsd_list/static/src/js/column_filter_panel.js',
            'sn_wsd_list/static/src/js/column_filter_panel.xml',
            'sn_wsd_list/static/src/js/list_renderer_patch.js',
            'sn_wsd_list/static/src/scss/column_filter.scss',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
