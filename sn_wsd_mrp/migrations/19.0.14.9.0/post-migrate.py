def migrate(cr, version):
    # 存量清单行按工序代码回填工序 m2o（同公司；code 优先，无 code 的
    # 工序按 name 匹配，与设备 API 的匹配口径一致）。对不上的行保持
    # m2o 为空，代码键原样保留。
    cr.execute("""
        UPDATE production_process_document d
        SET operation_id = o.id
        FROM sn_wsd_operation o
        WHERE d.operation_id IS NULL
          AND d.company_id = o.company_id
          AND (o.code = d.route_operation_code
               OR (o.code IS NULL AND o.name = d.route_operation_code))
    """)
