def migrate(cr, version):
    """Composite index for the "current operation per SN" projection.

    The one-scan station kernel keeps no parking rows: a board's position is
    the operation of its latest pass record, read as
    ``WHERE mes_order_id = %s GROUP BY serial_identity_id, max(id)`` (floor
    data counters/list, batch-pass candidate selection). This index turns
    that projection into an index-only scan.
    """
    cr.execute("""
        CREATE INDEX IF NOT EXISTS sn_wsd_serial_op_history_order_serial_idx
        ON sn_wsd_serial_operation_history
           (mes_order_id, serial_identity_id, id)
    """)
