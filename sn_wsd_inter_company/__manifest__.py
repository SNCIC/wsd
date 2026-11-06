{
    'name': 'SN WSD Inter-Company Rules',
    'version': '19.0.2.2.2',
    'summary': 'Two-way trade agreements between the companies of the database',
    'category': 'Productivity',
    'description': '''Synchronize documents between the companies of the same database.

A trade agreement links two companies, with one switch per direction, so both
companies can sell to each other at the same time. Confirming a sale order
generates the purchase order of the buyer, approving a purchase order
generates the sales order of the seller, posting a customer invoice generates
the vendor bill, and validating a delivery fills the receipt.

Beyond creation, the agreement says how far the two documents follow each
other: later changes of the editable counterpart are pushed, cancelling the
source document cancels or flags the counterpart, and deleting a document
deletes or is refused depending on the state of the other side. Every
synchronization is logged, conflicts are detected from the previous snapshot,
and the inconsistencies found by the daily check land in a queue of issues.''',
    'depends': [
        'sale_management',
        'purchase',
        'sale_purchase',
        'sale_stock',
        'purchase_stock',
        'account',
        'sn_wsd_code_rule',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/company_rules.xml',
        'data/intercompany_cron.xml',
        'views/intercompany_agreement_views.xml',
        'views/intercompany_product_map_views.xml',
        'views/intercompany_sync_log_views.xml',
        'views/intercompany_sync_issue_views.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/res_company_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'author': 'SNCIC',
    'license': 'LGPL-3',
}
