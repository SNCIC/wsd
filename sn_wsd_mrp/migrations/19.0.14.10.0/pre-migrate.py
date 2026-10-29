def _table_exists(cr, table_name):
    cr.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_name = %s)", (table_name,))
    return cr.fetchone()[0]


def _column_exists(cr, table_name, column_name):
    cr.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s)",
        (table_name, column_name))
    return cr.fetchone()[0]


def migrate(cr, version):
    """Prepare the selection->many2one swap of x_process_section.

    The ORM converts the existing varchar column in place (varchar->int);
    legacy keys like 'smt' would abort that cast, and the required stat
    column cannot hold NULLs. So: stash, blank the operation column, and
    move the stat rows aside entirely (post-migrate recreates them).
    """
    if _table_exists(cr, 'sn_wsd_operation') and \
            _column_exists(cr, 'sn_wsd_operation', 'x_process_section'):
        cr.execute("""
            CREATE TABLE tmp_ps_migration_operation AS
            SELECT id, x_process_section
              FROM sn_wsd_operation
             WHERE x_process_section IS NOT NULL
        """)
        # NULLs cast cleanly to integer during the ORM column conversion
        cr.execute(
            'UPDATE sn_wsd_operation SET x_process_section = NULL '
            'WHERE x_process_section IS NOT NULL')
    if _table_exists(cr, 'sn_wsd_route_section_stat') and \
            _column_exists(cr, 'sn_wsd_route_section_stat', 'x_process_section'):
        cr.execute(
            'CREATE TABLE tmp_ps_migration_stat AS '
            'SELECT * FROM sn_wsd_route_section_stat')
        cr.execute('DELETE FROM sn_wsd_route_section_stat')
