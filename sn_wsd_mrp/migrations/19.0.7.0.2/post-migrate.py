import logging

from odoo.tools import sql


_logger = logging.getLogger(__name__)


def _sync_private_route_operation_flags(cr):
    required = (
        'x_allow_serial_creation',
        'x_allow_reentry',
        'x_allow_repair_return',
        'x_allow_skip_with_override',
        'x_ng_retry_limit',
    )
    tables = (
        'sn_wsd_mes_order_route_operation',
        'sn_wsd_mes_order_route',
        'sn_wsd_process_route_operation',
    )
    if any(not sql.table_exists(cr, table) for table in tables):
        return
    if any(not sql.column_exists(cr, 'sn_wsd_mes_order_route_operation', column) for column in required):
        return
    if any(not sql.column_exists(cr, 'sn_wsd_process_route_operation', column) for column in required):
        return

    cr.execute(
        """
        UPDATE sn_wsd_mes_order_route_operation AS private_op
           SET x_allow_serial_creation = COALESCE(common_op.x_allow_serial_creation, FALSE),
               x_allow_reentry = COALESCE(common_op.x_allow_reentry, FALSE),
               x_allow_repair_return = COALESCE(common_op.x_allow_repair_return, FALSE),
               x_allow_skip_with_override = COALESCE(common_op.x_allow_skip_with_override, FALSE),
               x_ng_retry_limit = COALESCE(common_op.x_ng_retry_limit, 0)
          FROM sn_wsd_mes_order_route private_route
          JOIN sn_wsd_process_route_operation common_op
            ON common_op.route_id = private_route.route_id
         WHERE private_op.mes_route_id = private_route.id
           AND common_op.operation_id = private_op.operation_id
           AND private_route.route_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM sn_wsd_serial_operation_history history
                WHERE history.route_operation_id = private_op.id
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM sn_wsd_mes_operation_report report
                WHERE report.route_operation_id = private_op.id
           )
        """
    )
    _logger.info(
        'sn_wsd_mrp 19.0.7.0.2: synchronized MES order route operation execution flags'
    )


def migrate(cr, version):
    if not version:
        return
    _sync_private_route_operation_flags(cr)
