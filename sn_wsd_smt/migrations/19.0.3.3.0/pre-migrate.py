def migrate(cr, version):
    cr.execute("""
        SELECT company_id, name, count(*)
        FROM sn_smt_feeder
        GROUP BY company_id, name
        HAVING count(*) > 1
    """)
    duplicates = cr.fetchall()
    if duplicates:
        raise ValueError(
            'Duplicate feeder SN per company, fix before upgrade: %s' % (duplicates,)
        )
    cr.execute("ALTER TABLE sn_smt_feeder ADD COLUMN IF NOT EXISTS feeder_sn VARCHAR")
    cr.execute("UPDATE sn_smt_feeder SET feeder_sn = name WHERE feeder_sn IS NULL OR feeder_sn = ''")
    cr.execute("UPDATE sn_smt_feeder SET status = 'normal' WHERE status = '1'")
    cr.execute("UPDATE sn_smt_feeder SET status = 'in_use' WHERE status = '2'")
    cr.execute("UPDATE sn_smt_feeder SET status = 'disabled' WHERE status = '9'")
