# Legacy selection -> seeded type row (name, thaw min, thaw max, stir control)
LEGACY_TYPES = [
    ('Solder Paste', 0, 120, True),
    ('Red Glue', 0, 133, True),
    ('Solder Wire', 0, 480, False),
    ('Solder Bar', 0, 480, False),
    ('Flux', 0, 480, False),
    ('Conformal Coating', 0, 480, False),
]
LEGACY_KEYS = [
    'solder_paste',
    'red_glue',
    'solder_wire',
    'solder_bar',
    'flux',
    'conformal_coating',
]


def migrate(cr, version):
    # The consumable type becomes a self-maintained table carrying the control
    # defaults (replacing the hard-coded selection -> defaults mapping).
    cr.execute("""
        CREATE TABLE IF NOT EXISTS sn_consumable_type (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL,
            thaw_duration_min INTEGER,
            thaw_duration_max INTEGER,
            thaw_count_limit INTEGER,
            stir_control BOOLEAN,
            stir_duration_min INTEGER,
            stir_duration_max INTEGER,
            active BOOLEAN DEFAULT TRUE,
            company_id INTEGER NOT NULL,
            create_uid INTEGER,
            create_date TIMESTAMP,
            write_uid INTEGER,
            write_date TIMESTAMP
        )
    """)

    # Seed the six legacy types for every company that already has templates
    # (plus the default company when the module has never been used).
    cr.execute("SELECT DISTINCT company_id FROM sn_consumable_template")
    company_ids = [row[0] for row in cr.fetchall()]
    if not company_ids:
        cr.execute("SELECT id FROM res_company ORDER BY id LIMIT 1")
        row = cr.fetchone()
        company_ids = [row[0]] if row else []
    for company_id in company_ids:
        for name, thaw_min, thaw_max, stir in LEGACY_TYPES:
            cr.execute(
                "INSERT INTO sn_consumable_type"
                " (name, thaw_duration_min, thaw_duration_max, stir_control, active, company_id)"
                " VALUES (%s, %s, %s, %s, TRUE, %s)",
                (name, thaw_min, thaw_max, stir, company_id))

    # Convert the template selection column to the new type_id m2o column.
    cr.execute("ALTER TABLE sn_consumable_template ADD COLUMN IF NOT EXISTS type_id INTEGER")
    for key, (name, _tmin, _tmax, _stir) in zip(LEGACY_KEYS, LEGACY_TYPES):
        cr.execute(
            "UPDATE sn_consumable_template t SET type_id = c.id"
            " FROM sn_consumable_type c"
            " WHERE c.company_id = t.company_id AND c.name = %s"
            " AND t.consumable_type = %s",
            (name, key))
    cr.execute("ALTER TABLE sn_consumable_template DROP COLUMN IF EXISTS consumable_type")

    # The info table's stored selection mirror is replaced by a related type_id
    # column the ORM adds and backfills during the same upgrade.
    cr.execute("ALTER TABLE sn_consumable_info DROP COLUMN IF EXISTS consumable_type")

    # Drop stale field metadata for the removed selection fields.
    cr.execute(
        "DELETE FROM ir_model_fields WHERE model IN ('sn.consumable.template', 'sn.consumable.info')"
        " AND name = 'consumable_type'"
    )
