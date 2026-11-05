import logging

from odoo.tools import sql


_logger = logging.getLogger(__name__)

# (table, old_column, new_column) of every live foreign key that pointed at
# sn.wsd.internal.serial and now points at sn.wsd.serial.identity.
FK_MIGRATIONS = [
    ('sn_wsd_quality_issue', 'internal_serial_id', 'serial_identity_id'),
    ('sn_wsd_serial_freeze', 'serial_id', 'serial_identity_id'),
    ('sn_wsd_quality_inspection', 'evidence_internal_serial_id', 'evidence_serial_identity_id'),
    ('sn_wsd_quality_inspection_sample', 'internal_serial_id', 'serial_identity_id'),
    ('sn_wsd_quality_inspection_defect_line', 'internal_serial_id', 'serial_identity_id'),
    ('sn_wsd_meter_component_binding', 'internal_serial_id', 'serial_identity_id'),
    ('sn_wsd_repair_order', 'serial_id', 'serial_identity_id'),
    ('sn_wsd_scrap_record', 'serial_id', 'serial_identity_id'),
    ('sn_wsd_mes_test_result', 'internal_serial_id', 'serial_identity_id'),
    ('sn_wsd_mes_test_result_detail', 'internal_serial_id', 'serial_identity_id'),
    ('sn_smt_material_consumption', 'internal_serial_id', 'serial_identity_id'),
    ('sn_wsd_meter_pack_record', 'serial_id', 'serial_identity_id'),
    # same-name column, comodel switched: remap values in place
    ('sn_smt_online_material', 'last_consumed_serial_id', 'last_consumed_serial_id'),
]


def _repoint_fks(cr):
    for table, old_column, new_column in FK_MIGRATIONS:
        if not sql.table_exists(cr, table):
            continue
        if not sql.column_exists(cr, table, old_column):
            continue
        if old_column == new_column:
            # comodel switch on the same column: remap in place
            cr.execute('''
                UPDATE %(table)s t
                   SET %(col)s = m.identity_id
                  FROM sn_unification_map m
                 WHERE t.%(col)s = m.internal_id
            ''' % {'table': table, 'col': new_column})
            cr.execute('''
                UPDATE %(table)s t
                   SET %(col)s = NULL
                 WHERE t.%(col)s IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM sn_unification_map m
                        WHERE m.internal_id = t.%(col)s)
            ''' % {'table': table, 'col': new_column})
            cr.execute('''
                SELECT conname FROM pg_constraint
                 WHERE contype = 'f' AND conrelid = %s::regclass
                   AND confrelid = 'sn_wsd_internal_serial'::regclass
            ''', [table])
            for (conname,) in cr.fetchall():
                cr.execute('ALTER TABLE %s DROP CONSTRAINT %s' % (table, conname))
            _logger.info('sn_wsd_mrp 19.0.8.0.0: remapped %s.%s in place',
                         table, new_column)
            continue
        if sql.column_exists(cr, table, new_column):
            # the ORM already created the new column (mrp's own models load
            # before this post-migrate): copy the mapped values over and drop
            # the old column instead of renaming
            cr.execute('''
                UPDATE %(table)s t
                   SET %(new_column)s = m.identity_id
                  FROM sn_unification_map m
                 WHERE t.%(old_column)s = m.internal_id
            ''' % {'table': table, 'old_column': old_column, 'new_column': new_column})
            cr.execute('''
                DELETE FROM %(table)s t
                 WHERE t.%(old_column)s IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM sn_unification_map m
                        WHERE m.internal_id = t.%(old_column)s)
            ''' % {'table': table, 'old_column': old_column})
            cr.execute('ALTER TABLE %s DROP COLUMN %s' % (table, old_column))
            _logger.info('sn_wsd_mrp 19.0.8.0.0: copied %s.%s from old column',
                         table, new_column)
            continue
        cr.execute('ALTER TABLE %s RENAME COLUMN %s TO %s' % (table, old_column, new_column))
        # drop the stale FK to the archive registry before repointing the ids;
        # the ORM recreates a proper FK towards the identity registry later
        cr.execute('''
            SELECT conname FROM pg_constraint
             WHERE contype = 'f' AND conrelid = %s::regclass
               AND confrelid = 'sn_wsd_internal_serial'::regclass
        ''', [table])
        for (conname,) in cr.fetchall():
            cr.execute('ALTER TABLE %s DROP CONSTRAINT %s' % (table, conname))
        cr.execute('''
            UPDATE %(table)s t
               SET %(new_column)s = m.identity_id
              FROM sn_unification_map m
             WHERE t.%(new_column)s = m.internal_id
        ''' % {'table': table, 'new_column': new_column})
        # rows still pointing at an unmapped archive (blank serial_no) are
        # junk from the old registry; remove them
        cr.execute('''
            DELETE FROM %(table)s t
             WHERE t.%(new_column)s IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM sn_unification_map m
                    WHERE m.internal_id = t.%(new_column)s)
        ''' % {'table': table, 'new_column': new_column})
        _logger.info('sn_wsd_mrp 19.0.8.0.0: repointed %s.%s', table, new_column)
    # NOT NULL columns whose rows lost the pointer: the pointerless rows are
    # junk from the archive registry (blank SN); remove them, then keep the
    # constraint.
    for table, column in [
        ('sn_wsd_quality_issue', 'serial_identity_id'),
        ('sn_wsd_repair_order', 'serial_identity_id'),
        ('sn_wsd_scrap_record', 'serial_identity_id'),
        ('sn_smt_material_consumption', 'serial_identity_id'),
        ('sn_wsd_meter_pack_record', 'serial_identity_id'),
    ]:
        if not sql.table_exists(cr, table) or not sql.column_exists(cr, table, column):
            continue
        cr.execute('DELETE FROM %s WHERE %s IS NULL' % (table, column))


def migrate(cr, version):
    if not version:
        return
    if not sql.table_exists(cr, 'sn_unification_map'):
        return
    # binding backfill from the snapshotted stage parent chain (product SN
    # built into the machine SN)
    if sql.table_exists(cr, 'sn_unification_parent'):
        cr.execute('''
            INSERT INTO sn_wsd_serial_binding
                (serial_identity_id, bound_serial_identity_id, binding_type,
                 binding_date, source, company_id)
            SELECT parent_map.identity_id, child_map.identity_id, 'machine',
                   chain.binding_date, 'manual', chain.company_id
              FROM sn_unification_parent chain
              JOIN sn_unification_map child_map ON child_map.internal_id = chain.internal_id
              JOIN sn_unification_map parent_map ON parent_map.internal_id = chain.parent_id
             WHERE parent_map.identity_id != child_map.identity_id
        ''')
        cr.execute('DROP TABLE IF EXISTS sn_unification_parent')
    _repoint_fks(cr)
    # legacy sequences of the removed archive registry
    cr.execute("""
        DELETE FROM ir_sequence
         WHERE code IN ('sn.wsd.internal.serial', 'sn.wsd.internal.serial.no')
    """)
    # finally drop the archive registry
    cr.execute('DROP TABLE IF EXISTS sn_wsd_internal_serial CASCADE')
    cr.execute('DROP TABLE IF EXISTS sn_unification_map')
    _logger.info('sn_wsd_mrp 19.0.8.0.0: stage-archive registry removed')
