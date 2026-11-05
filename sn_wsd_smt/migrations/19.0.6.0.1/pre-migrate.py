def migrate(cr, version):
    # 同公司+图号+面别+产线 挂在多张有效料站表 = 新 constrains 拒收的存量
    # 脏数据（constrains 只拦新写）。报出来人工清理（作废多余表或摘线）
    # 后重跑升级；干净库零作用。
    cr.execute("""
        SELECT t.company_id, t.model_code, t.product_side,
               l.production_line_id, array_agg(t.table_name ORDER BY t.id)
        FROM sn_smt_material_table_line l
        JOIN sn_smt_material_table t ON t.id = l.table_id
        WHERE t.is_valid = 'Y'
        GROUP BY t.company_id, t.model_code, t.product_side, l.production_line_id
        HAVING count(DISTINCT t.id) > 1
    """)
    duplicates = cr.fetchall()
    if duplicates:
        raise ValueError(
            'Production line linked to multiple valid material tables '
            '(company_id, model_code, side, line_id, table_names), fix '
            'before upgrade: %s' % (duplicates,)
        )
