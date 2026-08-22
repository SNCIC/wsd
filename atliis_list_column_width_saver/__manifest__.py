# -*- coding: utf-8 -*-
##############################################################################
#    Copyright (C) 2026 — Atliis 360
#    Developed by Atliis 360
#    Licensed under the OPL-1 License
##############################################################################oding: utf-8 -*-
{
    "name": "Odoo UI Enhancer – Save List Column Width Automatically",
    "version": "19.0.0.1",
    "summary": "Stop resizing columns every time – automatically save and restore your layout",
    "description": """
Tired of resizing columns every time you open a list view?

Odoo UI Enhancer automatically saves your preferred column widths so you never have to adjust them again.

🚀 Key Benefits
--------------
- Save time by avoiding repeated column resizing
- Keep your preferred layout across sessions
- Improve daily productivity for Odoo users
- Enjoy a cleaner and more consistent interface

⚡ Main Features
--------------
- Automatically save resized column widths
- Restore layout after page refresh and navigation
- Works across all list/tree views
- User-specific and view-specific persistence
- Reset widths anytime using the standard header controls

🎯 Perfect For
--------------
- Odoo users working daily in list views
- Teams handling large datasets
- Power users who value efficiency

💡 Result
---------
A smoother, faster, and frustration-free Odoo experience.

""",
    "category": "Tools",
    "author": "Atliis 360",
    "maintainer": "Atliis 360",
    "website": "https://www.atliis.com",
    "support": "helpdesk@atliis.com",
    "live_test_url": "https://demov19.atliis.com/web/login?utm_source=odoo_apps&utm_medium=live_preview&utm_campaign=atliis_list_column_width_saver",
    "price": 0.0,
    "currency": "USD",
    "license": "OPL-1",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "atliis_list_column_width_saver/static/src/js/list_column_width_persistence.js",
        ],
    },
    "images": [
        "static/description/banner.png",
        "static/description/icon.png",
    ],
    "installable": True,
    "application": False,
}
