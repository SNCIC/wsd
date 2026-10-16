def migrate(cr, version):
    # 工艺文件类型名称转可翻译字段（varchar → jsonb，原值落 en_US 保底）；
    # po 里的 zh_CN 类型名（参数计划等四个默认类型）随升级载入。
    cr.execute("""
        ALTER TABLE production_process_doc_type
        ALTER COLUMN name TYPE jsonb
        USING jsonb_build_object('en_US', name)
    """)
