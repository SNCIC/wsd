import logging

from odoo.tools import sql

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    # station-pass-count：允许多行 OK（复测/返工回访），删除"至多一行 ok"
    # 的部分唯一索引（19.0.7.1.0 建立）。
    if sql.table_exists(cr, 'sn_wsd_serial_operation_history'):
        cr.execute(
            "DROP INDEX IF EXISTS "
            "sn_wsd_serial_operation_history_ok_uniq")
    # 过站次数上限必填且 ≥1（0=不限废弃）：存量统一刷新为 1（测试数据）。
    if sql.table_exists(cr, 'sn_wsd_operation') \
            and sql.column_exists(cr, 'sn_wsd_operation', 'x_max_test_count'):
        cr.execute(
            "UPDATE sn_wsd_operation SET x_max_test_count = 1 "
            "WHERE x_max_test_count IS NULL OR x_max_test_count < 1")
    _logger.info(
        'sn_wsd_mrp 19.0.10.0.0: dropped ok-row unique index; refreshed '
        'max test count to >= 1')
