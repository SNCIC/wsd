import logging

from odoo.tools import sql


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    # Stage archives still exist at this point (pre runs before any model
    # processing): build the identity registry and the id mapping that the
    # post-migration uses to repoint every foreign key.
    if not sql.table_exists(cr, 'sn_wsd_internal_serial'):
        return
    cr.execute('DROP TABLE IF EXISTS sn_unification_map')
    cr.execute('''
        CREATE TABLE sn_unification_map (
            internal_id INTEGER PRIMARY KEY,
            identity_id INTEGER NOT NULL
        )
    ''')
    # 1) archives already bridged to an identity: reuse it
    cr.execute('''
        INSERT INTO sn_unification_map (internal_id, identity_id)
        SELECT s.id, s.serial_identity_id
          FROM sn_wsd_internal_serial s
         WHERE s.serial_identity_id IS NOT NULL
    ''')
    # 2) archives without a bridge: find an identity by name, else create one
    cr.execute('''
        SELECT s.id, s.serial_no, s.company_id
          FROM sn_wsd_internal_serial s
         WHERE s.serial_identity_id IS NULL
    ''')
    for internal_id, serial_no, company_id in cr.fetchall():
        serial_no = (serial_no or '').strip()
        if not serial_no:
            continue
        cr.execute('''
            SELECT id FROM sn_wsd_serial_identity
             WHERE name = %s AND company_id = %s
             LIMIT 1
        ''', [serial_no, company_id])
        row = cr.fetchone()
        if row:
            identity_id = row[0]
        else:
            cr.execute('''
                INSERT INTO sn_wsd_serial_identity
                    (name, company_id, origin_type, active)
                VALUES (%s, %s, 'migration', true)
                RETURNING id
            ''', [serial_no, company_id])
            identity_id = cr.fetchone()[0]
        cr.execute(
            'INSERT INTO sn_unification_map (internal_id, identity_id) '
            'VALUES (%s, %s) ON CONFLICT DO NOTHING',
            [internal_id, identity_id])
    # 3) snapshot the stage parent chain: the binding table only exists in
    #    post-migrate, and the archive table may be gone by then
    cr.execute('DROP TABLE IF EXISTS sn_unification_parent')
    cr.execute('''
        CREATE TABLE sn_unification_parent AS
        SELECT s.id AS internal_id, s.parent_id, s.company_id,
               COALESCE(s.entry_time, s.create_date, now()) AS binding_date
          FROM sn_wsd_internal_serial s
         WHERE s.parent_id IS NOT NULL
    ''')
    cr.execute('SELECT count(*) FROM sn_unification_map')
    _logger.info(
        'sn_wsd_mrp 19.0.8.0.0 pre: mapped %s stage archives to identities',
        cr.fetchone()[0])
