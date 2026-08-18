import logging

from odoo.tools import sql


_logger = logging.getLogger(__name__)


def _has_columns(cr, table_name, column_names):
    return (
        sql.table_exists(cr, table_name)
        and all(sql.column_exists(cr, table_name, column) for column in column_names)
    )


def _backfill_mes_order_from_workorder(cr, table_name):
    if not _has_columns(cr, table_name, ('workorder_id', 'mes_order_id')):
        return
    if not _has_columns(cr, 'mrp_workorder', ('id', 'x_mes_order_id')):
        return
    cr.execute(
        f"""
        UPDATE {table_name} target
           SET mes_order_id = workorder.x_mes_order_id
          FROM mrp_workorder workorder
         WHERE target.workorder_id = workorder.id
           AND target.mes_order_id IS NULL
           AND workorder.x_mes_order_id IS NOT NULL
        """
    )


def _backfill_route_operation_from_workorder(cr, table_name):
    required_target = ('workorder_id', 'mes_order_id', 'route_operation_id')
    if not _has_columns(cr, table_name, required_target):
        return
    required_workorder = ('id', 'operation_id')
    if not _has_columns(cr, 'mrp_workorder', required_workorder):
        return
    if not _has_columns(cr, 'mrp_routing_workcenter', ('id', 'x_route_operation_id')):
        return
    route_tables = (
        'sn_wsd_mes_order_route',
        'sn_wsd_mes_order_route_operation',
    )
    if any(not sql.table_exists(cr, table) for table in route_tables):
        return

    cr.execute(
        f"""
        WITH resolved AS (
            SELECT target.id AS target_id,
                   private_op.id AS route_operation_id
              FROM {table_name} target
              JOIN mrp_workorder workorder
                ON workorder.id = target.workorder_id
              JOIN mrp_routing_workcenter bom_op
                ON bom_op.id = workorder.operation_id
              JOIN sn_wsd_mes_order_route private_route
                ON private_route.mes_order_id = target.mes_order_id
              JOIN sn_wsd_mes_order_route_operation private_op
                ON private_op.mes_route_id = private_route.id
              JOIN sn_wsd_process_route_operation common_op
                ON common_op.id = bom_op.x_route_operation_id
               AND common_op.operation_id = private_op.operation_id
             WHERE target.route_operation_id IS NULL
               AND target.mes_order_id IS NOT NULL
               AND bom_op.x_route_operation_id IS NOT NULL
        )
        UPDATE {table_name} target
           SET route_operation_id = resolved.route_operation_id
          FROM resolved
         WHERE target.id = resolved.target_id
        """
    )


def _backfill_child_related_fields(cr):
    if _has_columns(cr, 'sn_wsd_mes_test_result_detail', ('test_result_id', 'mes_order_id', 'route_operation_id')):
        cr.execute(
            """
            UPDATE sn_wsd_mes_test_result_detail detail
               SET mes_order_id = test_result.mes_order_id,
                   route_operation_id = test_result.route_operation_id
              FROM sn_wsd_mes_test_result test_result
             WHERE detail.test_result_id = test_result.id
               AND (
                   detail.mes_order_id IS NULL
                   OR detail.route_operation_id IS NULL
               )
            """
        )
    if _has_columns(cr, 'sn_wsd_aoi_defect_detail', ('test_result_id', 'mes_order_id', 'route_operation_id')):
        cr.execute(
            """
            UPDATE sn_wsd_aoi_defect_detail detail
               SET mes_order_id = test_result.mes_order_id,
                   route_operation_id = test_result.route_operation_id
              FROM sn_wsd_mes_test_result test_result
             WHERE detail.test_result_id = test_result.id
               AND (
                   detail.mes_order_id IS NULL
                   OR detail.route_operation_id IS NULL
               )
            """
        )


def migrate(cr, version):
    if not version:
        return
    for table_name in ('sn_wsd_mes_sn_travel', 'sn_wsd_mes_test_result'):
        _backfill_mes_order_from_workorder(cr, table_name)
        _backfill_route_operation_from_workorder(cr, table_name)
    for table_name in (
        'sn_wsd_mes_nameplate_binding',
        'sn_wsd_mes_packaging_record',
        'sn_wsd_mes_tooling_usage_log',
        'sn_wsd_mes_process_parameter_validation',
    ):
        _backfill_mes_order_from_workorder(cr, table_name)
        _backfill_route_operation_from_workorder(cr, table_name)
    _backfill_child_related_fields(cr)
    _logger.info(
        'sn_wsd_api 19.0.3.2.8: backfilled MES order route operation references'
    )
