import logging

from odoo.tools import sql


_logger = logging.getLogger(__name__)

DROPPED_COLUMNS = ('x_allow_reentry', 'x_allow_repair_return', 'x_ng_retry_limit')
DROPPED_TABLES = (
    'sn_wsd_mes_order_route_operation',
    'sn_wsd_process_route_operation',
    'mrp_routing_workcenter',
)


def _drop_legacy_route_columns(cr):
    for table in DROPPED_TABLES:
        if not sql.table_exists(cr, table):
            continue
        for column in DROPPED_COLUMNS:
            if sql.column_exists(cr, table, column):
                cr.execute('ALTER TABLE %s DROP COLUMN %s' % (table, column))
    _logger.info(
        'sn_wsd_mrp 19.0.7.1.0: dropped legacy route columns %s',
        ', '.join(DROPPED_COLUMNS),
    )


def _relax_history_uniqueness(cr):
    """The full (SN, operation) unique index blocked NG re-entries; keep only
    the real invariant: at most one result='ok' row per (SN, operation)."""
    table = 'sn_wsd_serial_operation_history'
    if not sql.table_exists(cr, table):
        return
    cr.execute(
        "ALTER TABLE %s DROP CONSTRAINT IF EXISTS _history_uniq" % table)
    cr.execute("DROP INDEX IF EXISTS _history_uniq")
    # pre-17 auto-named variants, just in case
    cr.execute(
        "DROP INDEX IF EXISTS %s_serial_identity_id_route_operation_id_uniq"
        % table)
    cr.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS sn_wsd_serial_operation_history_ok_uniq
            ON sn_wsd_serial_operation_history (serial_identity_id, route_operation_id)
            WHERE result = 'ok'
        """
    )
    _logger.info(
        'sn_wsd_mrp 19.0.7.1.0: history uniqueness relaxed to one ok row '
        'per (SN, operation)'
    )


def migrate(cr, version):
    if not version:
        return
    _relax_history_uniqueness(cr)
    _drop_legacy_route_columns(cr)
