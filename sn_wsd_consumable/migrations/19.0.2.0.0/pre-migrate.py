def migrate(cr, version):
    # Full rebuild of the module: legacy tables are empty, drop them and let
    # the ORM recreate the rebuilt models from scratch. CASCADE handles the
    # legacy FK from the template table to the barcode-rule table.
    cr.execute("DROP TABLE IF EXISTS sn_consumable_barcode_rule CASCADE")
    cr.execute("DROP TABLE IF EXISTS sn_consumable_template CASCADE")
    cr.execute("DROP TABLE IF EXISTS sn_consumable_info CASCADE")
    # Remove obsolete menu/view/action/window records so the rewritten data
    # files recreate them cleanly (the old barcode-rule model is gone).
    for table, model in [
        ('ir_ui_menu', 'ir.ui.menu'),
        ('ir_ui_view', 'ir.ui.view'),
        ('ir_act_window', 'ir.actions.act_window'),
        ('ir_model_access', 'ir.model.access'),
    ]:
        cr.execute(
            "DELETE FROM %s WHERE id IN ("
            " SELECT res_id FROM ir_model_data"
            " WHERE module = 'sn_wsd_consumable' AND model = %%s)" % table,
            (model,),
        )
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = 'sn_wsd_consumable' AND model = %s",
            (model,),
        )
    cr.execute(
        "DELETE FROM ir_model_fields WHERE model IN"
        " ('sn.consumable.barcode.rule', 'sn.consumable.template', 'sn.consumable.info')"
    )
    cr.execute("DELETE FROM ir_model WHERE model = 'sn.consumable.barcode.rule'")
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'sn_wsd_consumable'"
        " AND name LIKE 'model_sn_consumable_barcode%%'"
    )
