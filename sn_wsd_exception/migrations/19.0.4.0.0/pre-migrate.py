# Full rebuild of sn_wsd_exception: legacy models sn.wsd.exception.record and
# sn.wsd.exception.type are retired for good and replaced by ticket/category/
# team/reason. Legacy tables are empty (dev stage), drop them and let the ORM
# recreate everything from the rewritten data files.

LEGACY_TABLES = [
    'sn_wsd_exception_record',
    'sn_wsd_exception_type',
    'sn_wsd_exception_record_attachment_rel',
    'sn_wsd_exception_type_notify_group_rel',
    'sn_wsd_exception_type_escalation_group_rel',
]

LEGACY_MODEL_NAMES = [
    'sn.wsd.exception.record',
    'sn.wsd.exception.type',
]

MODULE = 'sn_wsd_exception'


def migrate(cr, version):
    for table in LEGACY_TABLES:
        cr.execute('DROP TABLE IF EXISTS "%s" CASCADE' % table)

    # Remove obsolete menu/view/action/access/sequence/cron/rule records so the
    # rewritten data files recreate them cleanly.
    for table, model in [
        ('ir_ui_menu', 'ir.ui.menu'),
        ('ir_ui_view', 'ir.ui.view'),
        ('ir_act_window', 'ir.actions.act_window'),
        ('ir_model_access', 'ir.model.access'),
        ('ir_sequence', 'ir.sequence'),
        ('ir_cron', 'ir.cron'),
        ('ir_rule', 'ir.rule'),
        ('ir_act_report_xml', 'ir.actions.report'),
        ('ir_module_category', 'ir.module.category'),
        ('res_groups', 'res.groups'),
        ('res_groups_privilege', 'res.groups.privilege'),
    ]:
        cr.execute(
            "DELETE FROM %s WHERE id IN ("
            " SELECT res_id FROM ir_model_data"
            " WHERE module = %%s AND model = %%s)" % table,
            (MODULE, model),
        )
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = %s AND model = %s",
            (MODULE, model),
        )

    # Field metadata of the rebuilt models is regenerated on upgrade.
    cr.execute(
        "DELETE FROM ir_model_fields WHERE model IN %s",
        (tuple(LEGACY_MODEL_NAMES),),
    )
    for meta_model in ('ir.model.fields', 'ir.model.constraint', 'ir.model.selection'):
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = %s AND model = %s",
            (MODULE, meta_model),
        )

    # Both legacy models are retired; new models use different names.
    cr.execute(
        "DELETE FROM ir_model WHERE model IN %s",
        (tuple(LEGACY_MODEL_NAMES),),
    )
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = %s AND model = 'ir.model'"
        " AND name IN %s",
        (MODULE, tuple('model_' + name.replace('.', '_') for name in LEGACY_MODEL_NAMES)),
    )
