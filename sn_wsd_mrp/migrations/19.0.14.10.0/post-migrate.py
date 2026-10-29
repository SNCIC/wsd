from odoo.api import Environment


def _table_exists(cr, table_name):
    cr.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_name = %s)", (table_name,))
    return cr.fetchone()[0]


LEGACY_SECTIONS = [
    ('smt', 'SMT', 10),
    ('dip', 'DIP', 20),
    ('board_test', 'Board Test', 30),
    ('assembly', 'Assembly', 40),
    ('testing', 'Testing', 50),
    ('inspection', 'Inspection', 60),
    ('packaging', 'Packaging', 70),
]


def _ensure_sections(env, company_ids):
    """Idempotently seed the default sections for each company; data XML
    only covers the main company and loads after migrations anyway."""
    section_by_key = {}
    Section = env['sn.wsd.process.section']
    for company_id in company_ids:
        for code, name, sequence in LEGACY_SECTIONS:
            section = Section.search([
                ('company_id', '=', company_id), ('code', '=', code)], limit=1)
            if not section:
                section = Section.create({
                    'name': name, 'code': code, 'sequence': sequence,
                    'company_id': company_id,
                })
            section_by_key[(company_id, code)] = section.id
    return section_by_key


def migrate(cr, version):
    has_op_tmp = _table_exists(cr, 'tmp_ps_migration_operation')
    has_stat_tmp = _table_exists(cr, 'tmp_ps_migration_stat')
    if not has_op_tmp and not has_stat_tmp:
        return
    env = Environment(cr, 2, {})  # SUPERUSER_ID
    company_ids = set()
    if has_op_tmp:
        # operations still exist; company read from the live table
        cr.execute(
            'SELECT DISTINCT r.company_id FROM tmp_ps_migration_operation t '
            'JOIN sn_wsd_operation r ON r.id = t.id')
        company_ids.update(row[0] for row in cr.fetchall())
    if has_stat_tmp:
        # stat rows were moved aside whole; company is a stored column there
        cr.execute('SELECT DISTINCT company_id FROM tmp_ps_migration_stat')
        company_ids.update(row[0] for row in cr.fetchall())
    section_by_key = _ensure_sections(env, company_ids or {env.company.id})

    if has_op_tmp:
        for (company_id, code), section_id in section_by_key.items():
            cr.execute(
                'UPDATE sn_wsd_operation r SET x_process_section = %s '
                'FROM tmp_ps_migration_operation t '
                'WHERE r.id = t.id AND t.x_process_section = %s '
                'AND r.company_id = %s',
                (section_id, code, company_id))
        cr.execute('DROP TABLE tmp_ps_migration_operation')

    if has_stat_tmp:
        cr.execute(
            'SELECT route_id, x_process_section, start_operation_id, '
            'end_operation_id, company_id FROM tmp_ps_migration_stat')
        StatLine = env['sn.wsd.route.section.stat']
        for route_id, key, start_op, end_op, company_id in cr.fetchall():
            section_id = section_by_key.get((company_id, key))
            if not section_id:
                continue
            StatLine.create({
                'route_id': route_id,
                'x_process_section': section_id,
                'start_operation_id': start_op,
                'end_operation_id': end_op,
                'company_id': company_id,
            })
        cr.execute('DROP TABLE tmp_ps_migration_stat')
    cr.commit()
