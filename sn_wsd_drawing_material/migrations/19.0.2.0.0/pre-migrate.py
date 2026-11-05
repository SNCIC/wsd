def migrate(cr, version):
    # 19.0.2.0.0: the three per-type reference columns merge into a single
    # Reference column (material_ref). Convert existing rows first, then drop
    # the old columns. material_type keeps its stored values, which match the
    # new computed mapping.
    cr.execute(
        "ALTER TABLE sn_wsd_drawing_material_line "
        "ADD COLUMN IF NOT EXISTS material_ref varchar")
    cr.execute(
        "UPDATE sn_wsd_drawing_material_line "
        "SET material_ref = 'sn.tooling.template,' || tooling_template_id "
        "WHERE tooling_template_id IS NOT NULL")
    cr.execute(
        "UPDATE sn_wsd_drawing_material_line "
        "SET material_ref = 'sn.consumable.template,' || consumable_template_id "
        "WHERE consumable_template_id IS NOT NULL")
    cr.execute(
        "UPDATE sn_wsd_drawing_material_line "
        "SET material_ref = 'product.product,' || product_id "
        "WHERE product_id IS NOT NULL")
    cr.execute(
        "ALTER TABLE sn_wsd_drawing_material_line DROP COLUMN tooling_template_id")
    cr.execute(
        "ALTER TABLE sn_wsd_drawing_material_line DROP COLUMN consumable_template_id")
    cr.execute(
        "ALTER TABLE sn_wsd_drawing_material_line DROP COLUMN product_id")
