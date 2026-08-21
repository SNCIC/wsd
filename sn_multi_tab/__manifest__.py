# -*- coding: utf-8 -*-
{
    'name': "SN Multi Tab",

    'summary': """
        sn multi tab plugin for odoo""",

    'description': """
        sn multi tab plugin
        multi tab,
        multi tab theme,
        odoo theme
    """,

    'author': 'sncic',
    'website': 'https://www.sncic.com',

    'category': 'Backend/Theme',
    'version': '19.0.1.0.0',
    'license': 'OPL-1',
    'images': ['static/description/banner.png'],

    'depends': ['base','web'],

    "application": False,
    "installable": True,
    "auto_install": False,

    'assets': {
        'web.assets_backend': [
    
            'sn_multi_tab/static/src/components/multi_tab/sn_multi_tab.scss',
            'sn_multi_tab/static/src/sn_action_container.scss',

            'sn_multi_tab/static/src/components/multi_tab/sn_multi_tab.js',
            'sn_multi_tab/static/src/components/multi_tab/sn_multi_tab.xml',
            
            'sn_multi_tab/static/src/sn_action_container.js',
            'sn_multi_tab/static/src/sn_action_service.js'
        ]
    }
}
