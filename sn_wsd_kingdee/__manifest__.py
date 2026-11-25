{
    "name": "SN WSD Kingdee Cloud Galaxy Integration",
    "version": "19.0.6.1",
    "category": "Tools",
    "summary": "Synchronize Odoo with Kingdee Cloud Galaxy (K/3 Cloud) through the WebAPI Python SDK",
    "author": "SNCIC",
    "website": "https://www.ylhctec.com",
    "license": "LGPL-3",
    # ``uom`` comes with ``product``; ``hr`` is needed by the department, employee and
    # job master data; ``stock`` by the warehouses and the batch master file.
    # ``purchase``, ``sale`` and ``mrp`` own the documents pushed to the account; they
    # are installed by the modules that extend them (sn_wsd_purchase, sn_wsd_sale,
    # sn_wsd_mrp), so depending on them here adds no module to the database.
    # ``account`` is depended on explicitly because the customer import resolves the
    # receivable condition through ``account.payment.term`` (see
    # models/account_payment_term.py); it is already installed by ``sale``/``purchase``.
    "depends": ["base", "web", "product", "hr", "stock", "purchase", "sale", "mrp",
                "account"],
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
        "data/kingdee_bill_maps.xml",
        "views/res_config_settings_views.xml",
        "views/kingdee_sync_log_views.xml",
        "views/product_views.xml",
        "views/account_payment_term_views.xml",
        "views/res_partner_views.xml",
        "views/kingdee_basedata_views.xml",
        "views/kingdee_sync_target_views.xml",
        "views/kingdee_account_views.xml",
        "views/kingdee_bill_map_views.xml",
        "views/kingdee_bill_document_views.xml",
        "views/kingdee_push_daily_views.xml",
        "views/kingdee_inventory_compare_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": True,
}
