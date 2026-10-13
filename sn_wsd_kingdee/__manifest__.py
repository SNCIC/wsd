{
    "name": "SN WSD Kingdee Cloud Galaxy Integration",
    "version": "19.0.2.1",
    "category": "Tools",
    "summary": "Synchronize Odoo with Kingdee Cloud Galaxy (K/3 Cloud) through the WebAPI Python SDK",
    "author": "SNCIC",
    "website": "https://www.ylhctec.com",
    "license": "LGPL-3",
    # ``uom`` comes with ``product``; ``hr`` is needed by the department master data
    # (BD_Department -> hr.department). Further applications (stock, account) are
    # added together with the object that needs them, never in advance.
    "depends": ["base", "web", "product", "hr"],
    # The Kingdee WebAPI SDK is delivered as a local wheel (it is not published
    # on PyPI). It is imported lazily by models/kingdee_client.py so this module
    # remains installable and configurable before the wheel is deployed.
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "security/kingdee_security.xml",
        "data/server_actions.xml",
        "data/ir_cron.xml",
        "data/kingdee_sync_targets.xml",
        "views/res_config_settings_views.xml",
        "views/kingdee_sync_log_views.xml",
        "views/product_views.xml",
        "views/res_partner_views.xml",
        "views/kingdee_basedata_views.xml",
        "views/kingdee_sync_target_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": True,
}
