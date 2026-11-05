from . import models
from . import controllers


def _migrate_growth_ids_to_bigint(cr):
    """Move ids/sequences of the device-volume growth tables (test results,
    test details, AOI defect lines, request logs) and the columns
    referencing them to bigint: at hundreds of thousands of rows per day
    the detail table exhausts int4 within a couple of years. Dependent SQL
    views are dropped and recreated verbatim."""
    GROWTH = [
        'sn_wsd_mes_test_result', 'sn_wsd_mes_test_result_detail',
        'sn_wsd_api_request_log', 'sn_wsd_aoi_defect_detail',
    ]
    cr.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = ANY(%s)", (GROWTH,))
    growth = [row[0] for row in cr.fetchall()]
    if not growth:
        return
    cr.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = 'id'", (growth[0],))
    if cr.fetchone()[0] == 'bigint':
        return  # already migrated

    # drop dependent SQL views
    cr.execute(
        "SELECT viewname FROM pg_views WHERE schemaname = 'public' AND ("
        + " OR ".join(["definition LIKE '%%%s%%'" % table for table in growth])
        + ")")
    views = cr.fetchall()
    view_defs = []
    for (view,) in views:
        cr.execute('SELECT pg_get_viewdef(%s, true)', (view,))
        view_defs.append((view, cr.fetchone()[0]))
        cr.execute('DROP VIEW %s' % view)

    # drop FKs referencing the growth tables
    cr.execute(
        "SELECT conname, conrelid::regclass::text, pg_get_constraintdef(oid) "
        "FROM pg_constraint WHERE contype = 'f' "
        "AND confrelid = ANY(%s::regclass[])", (growth,))
    fks = cr.fetchall()
    for name, table, _definition in fks:
        cr.execute('ALTER TABLE %s DROP CONSTRAINT %s' % (table, name))

    for table in growth:
        cr.execute('ALTER TABLE %s ALTER COLUMN id TYPE bigint' % table)
        cr.execute('ALTER SEQUENCE %s_id_seq AS bigint' % table)

    # referencing columns follow the bigint target
    cr.execute(
        "SELECT conrelid::regclass::text, a.attname "
        "FROM pg_constraint c "
        "JOIN unnest(c.conkey) AS k(attnum) ON TRUE "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
        "WHERE contype = 'f' AND confrelid = ANY(%s::regclass[])", (growth,))
    fk_cols = cr.fetchall()
    for table, column in fk_cols:
        cr.execute('ALTER TABLE %s ALTER COLUMN %s TYPE bigint' % (table, column))

    for name, table, definition in fks:
        cr.execute('ALTER TABLE %s ADD CONSTRAINT %s %s' % (table, name, definition))
    for view, definition in view_defs:
        cr.execute('CREATE VIEW %s AS %s' % (view, definition))


def _post_init_hook_bigint_ids(env):
    _migrate_growth_ids_to_bigint(env.cr)
