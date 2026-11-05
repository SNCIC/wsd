LEGACY_TABLES = [
    'sn_tooling',
    'sn_tooling_applicability',
    'sn_tooling_maintenance_log',
    'sn_tooling_maintenance_log_line',
    'sn_tooling_maintenance_wizard',
    'sn_tooling_maintenance_wizard_line',
    'sn_tooling_operation_log',
    'sn_tooling_pda_wizard',
    'sn_tooling_sn_tooling_maintenance_wizard_rel',
    'sn_tooling_template',
    'sn_tooling_template_maintenance_item',
    'sn_tooling_usage_log',
]

LEGACY_MODEL_NAMES = [
    'sn.tooling',
    'sn.tooling.applicability',
    'sn.tooling.maintenance.log',
    'sn.tooling.maintenance.log.line',
    'sn.tooling.maintenance.wizard',
    'sn.tooling.maintenance.wizard.line',
    'sn.tooling.operation.log',
    'sn.tooling.pda.wizard',
    'sn.tooling.template',
    'sn.tooling.template.maintenance.item',
    'sn.tooling.usage.log',
]

# Model names retired for good; sn.tooling, sn.tooling.template and
# sn.tooling.template.maintenance.item are reused by the rebuild.
RETIRED_MODEL_NAMES = [
    'sn.tooling.applicability',
    'sn.tooling.maintenance.log',
    'sn.tooling.maintenance.log.line',
    'sn.tooling.maintenance.wizard',
    'sn.tooling.maintenance.wizard.line',
    'sn.tooling.operation.log',
    'sn.tooling.pda.wizard',
    'sn.tooling.usage.log',
]


def migrate(cr, version):
    # Full rebuild of the module: legacy tables are empty, drop them (CASCADE
    # handles FK dependencies among them) and let the ORM recreate everything.
    for table in LEGACY_TABLES:
        cr.execute('DROP TABLE IF EXISTS "%s" CASCADE' % table)

    module = 'sn_wsd_tooling'
    # Remove obsolete menu/view/action/access/sequence records so the
    # rewritten data files recreate them cleanly.
    for table, model in [
        ('ir_ui_menu', 'ir.ui.menu'),
        ('ir_ui_view', 'ir.ui.view'),
        ('ir_act_window', 'ir.actions.act_window'),
        ('ir_model_access', 'ir.model.access'),
        ('ir_sequence', 'ir.sequence'),
    ]:
        cr.execute(
            "DELETE FROM %s WHERE id IN ("
            " SELECT res_id FROM ir_model_data"
            " WHERE module = %%s AND model = %%s)" % table,
            (module, model),
        )
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = %s AND model = %s",
            (module, model),
        )

    # Field metadata of the rebuilt models is regenerated on upgrade.
    cr.execute(
        "DELETE FROM ir_model_fields WHERE model IN %s",
        (tuple(LEGACY_MODEL_NAMES),),
    )
    for meta_model in ('ir.model.fields', 'ir.model.constraint', 'ir.model.selection'):
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = %s AND model = %s",
            (module, meta_model),
        )

    # Retired models disappear from the registry; reused names stay.
    cr.execute(
        "DELETE FROM ir_model WHERE model IN %s",
        (tuple(RETIRED_MODEL_NAMES),),
    )
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = %s AND model = 'ir.model'"
        " AND name IN %s",
        (module, tuple('model_' + name.replace('.', '_') for name in RETIRED_MODEL_NAMES)),
    )
