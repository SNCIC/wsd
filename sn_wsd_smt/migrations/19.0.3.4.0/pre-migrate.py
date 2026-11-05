def migrate(cr, version):
    cr.execute("""
        SELECT company_id, name, count(*)
        FROM sn_smt_cart
        GROUP BY company_id, name
        HAVING count(*) > 1
    """)
    duplicates = cr.fetchall()
    if duplicates:
        raise ValueError(
            'Duplicate cart SN per company, fix before upgrade: %s' % (duplicates,)
        )
    cr.execute("ALTER TABLE sn_smt_cart ADD COLUMN IF NOT EXISTS cart_sn VARCHAR")
    cr.execute("UPDATE sn_smt_cart SET cart_sn = name WHERE cart_sn IS NULL OR cart_sn = ''")
    cr.execute("UPDATE sn_smt_cart SET status = 'idle' WHERE status = '0'")
    cr.execute("UPDATE sn_smt_cart SET status = 'loaded' WHERE status = '1'")
