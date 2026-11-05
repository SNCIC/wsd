def migrate(cr, version):
    # The rework entry selection moved from the process-route definition step
    # (mrp.production.x_route_id based) to the MES order operation itself.
    # The repair tables are empty: drop the legacy column and its metadata.
    cr.execute("ALTER TABLE sn_wsd_repair_order DROP COLUMN IF EXISTS repair_entry_step_id")
    cr.execute(
        "DELETE FROM ir_model_fields WHERE model = 'sn.wsd.repair.order'"
        " AND name IN ('repair_entry_step_id', 'repair_process_route_id')"
    )
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'sn_wsd_repair'"
        " AND model = 'ir.model.fields'"
        " AND name IN ("
        " 'field_sn_wsd_repair_order__repair_entry_step_id',"
        " 'field_sn_wsd_repair_order__repair_process_route_id')"
    )
    # The repair type dictionary is gone: the repair mode now derives from
    # the MES order management mode (station -> sn, report -> qty).
    cr.execute("DROP TABLE IF EXISTS sn_wsd_repair_type CASCADE")
    cr.execute("ALTER TABLE sn_wsd_repair_order DROP COLUMN IF EXISTS repair_type_id")
    cr.execute(
        "DELETE FROM ir_model_fields WHERE model = 'sn.wsd.repair.order' AND name = 'repair_type_id'"
    )
    cr.execute("DELETE FROM ir_model WHERE model = 'sn.wsd.repair.type'")
    for meta_model in ('ir.model', 'ir.model.fields'):
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = 'sn_wsd_repair' AND model = %s"
            " AND (name LIKE 'model_sn_wsd_repair_type%%' OR name LIKE 'field_sn_wsd_repair_type%%')",
            (meta_model,),
        )
    for table, model in [
        ('ir_ui_menu', 'ir.ui.menu'),
        ('ir_ui_view', 'ir.ui.view'),
        ('ir_act_window', 'ir.actions.act_window'),
        ('ir_model_access', 'ir.model.access'),
    ]:
        cr.execute(
            "DELETE FROM %s WHERE id IN (SELECT res_id FROM ir_model_data"
            " WHERE module = 'sn_wsd_repair' AND model = %%s"
            " AND name IN ('menu_sn_wsd_repair_type', 'view_sn_wsd_repair_type_list',"
            " 'view_sn_wsd_repair_type_form', 'action_sn_wsd_repair_type'))" % table,
            (model,),
        )
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = 'sn_wsd_repair' AND model = %s"
            " AND name IN ('menu_sn_wsd_repair_type', 'view_sn_wsd_repair_type_list',"
            " 'view_sn_wsd_repair_type_form', 'action_sn_wsd_repair_type')",
            (model,),
        )
    cr.execute(
        "DELETE FROM ir_ui_menu WHERE id IN (SELECT res_id FROM ir_model_data"
        " WHERE module = 'sn_wsd_repair' AND model = 'ir.ui.menu'"
        " AND name = 'menu_sn_wsd_repair_order_line')")
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'sn_wsd_repair' AND model = 'ir.ui.menu'"
        " AND name = 'menu_sn_wsd_repair_order_line'")
