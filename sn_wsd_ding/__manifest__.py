{
    "name": "SN WSD DingTalk Integration",
    "version": "19.0.1.0",
    "category": "Tools",
    "summary": "Integrate DingTalk users and approvals with Odoo",
    "author": "SNCIC",
    "website": "https://www.ylhctec.com",
    "external_dependencies": {"python": ["alibabacloud_dingtalk", "pycryptodome"]},
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/server_actions.xml",
        "data/server_actions_instance.xml",
        "views/res_config_settings_views.xml",
        "views/res_users_views.xml",
        "views/dingding_approval_views.xml",
        "views/dingding_approval_field_views.xml",
        "views/dingding_approval_instance_views.xml",
        "views/menu.xml"
    ],
    "installable": True,
    "application": True,
    "icon": "sn_wsd_ding/static/description/icon.png",
    "license": "LGPL-3"
}
