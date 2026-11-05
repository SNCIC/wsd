LEGACY_TABLES = [
    'sn_wsd_incoming_material_label_wizard',
    'sn_wsd_incoming_material_label_wizard_line',
]

LEGACY_MODELS = [
    'sn.wsd.incoming.material.label.wizard',
    'sn.wsd.incoming.material.label.wizard.line',
]


def migrate(cr, version):
    for table in LEGACY_TABLES:
        cr.execute('DROP TABLE IF EXISTS "%s" CASCADE' % table)

    module = 'sn_wsd_stock'
    legacy_records = [
        ('ir.ui.view', 'view_incoming_material_label_wizard_form', 'ir_ui_view'),
        ('ir.ui.view', 'view_picking_form_reel_split', 'ir_ui_view'),
        (
            'ir.model.access',
            'access_sn_wsd_incoming_material_label_wizard_user',
            'ir_model_access',
        ),
        (
            'ir.model.access',
            'access_sn_wsd_incoming_material_label_wizard_line_user',
            'ir_model_access',
        ),
    ]
    for model, name, table in legacy_records:
        cr.execute(
            "DELETE FROM %s WHERE id IN ("
            " SELECT res_id FROM ir_model_data"
            " WHERE module = %%s AND model = %%s AND name = %%s)" % table,
            (module, model, name),
        )
        cr.execute(
            "DELETE FROM ir_model_data"
            " WHERE module = %s AND model = %s AND name = %s",
            (module, model, name),
        )

    cr.execute("DELETE FROM ir_model_fields WHERE model IN %s", (tuple(LEGACY_MODELS),))
    cr.execute("DELETE FROM ir_model WHERE model IN %s", (tuple(LEGACY_MODELS),))
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = %s AND model = 'ir.model'"
        " AND name IN %s",
        (
            module,
            tuple('model_' + model.replace('.', '_') for model in LEGACY_MODELS),
        ),
    )
