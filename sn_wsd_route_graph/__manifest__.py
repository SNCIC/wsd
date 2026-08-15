{
    'name': 'SN WSD Route Graph Editor',
    'version': '19.0.2.0.0',
    'summary': 'AntV X6 directed graph editor for process routes',
    'description': """
Full-screen directed-graph editor (AntV X6) for sn.wsd.process.route.
Backend methods get_route_graph / save_route_graph live in sn_wsd_mrp.
First version loads X6 from CDN; swap to a local static asset for production.
""",
    'depends': ['sn_wsd_mrp', 'web'],
    'data': [
        'views/route_graph_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sn_wsd_route_graph/static/lib/x6.js',
            'sn_wsd_route_graph/static/src/xml/route_graph_templates.xml',
            'sn_wsd_route_graph/static/src/js/route_graph_editor.js',
            'sn_wsd_route_graph/static/src/js/route_flow_widget.js',
            'sn_wsd_route_graph/static/src/js/route_form_actions.js',
            'sn_wsd_route_graph/static/src/js/route_flow_viewer.js',
            'sn_wsd_route_graph/static/src/js/route_version_compare.js',
        ],
    },
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
