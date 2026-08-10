import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        INSERT INTO sn_wsd_operation_workcenter_rel (operation_id, workcenter_id)
        SELECT operation_id, legacy_workcenter_id
          FROM sn_wsd_mrp_migration_workcenter
         WHERE operation_id IS NOT NULL
           AND legacy_workcenter_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    cr.execute(
        """
        INSERT INTO sn_wsd_operation_workcenter_rel (operation_id, workcenter_id)
        SELECT route_operation.operation_id, bom_operation.workcenter_id
          FROM sn_wsd_process_route_operation route_operation
          JOIN mrp_routing_workcenter bom_operation
            ON bom_operation.x_route_operation_id = route_operation.id
         WHERE route_operation.operation_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    cr.execute(
        """
        UPDATE sn_wsd_operation operation
           SET x_station_type = source.station_type
          FROM (
                SELECT operation_id, min(legacy_station_type) AS station_type
                  FROM sn_wsd_mrp_migration_workcenter
                 WHERE operation_id IS NOT NULL
                   AND legacy_station_type IS NOT NULL
                 GROUP BY operation_id
               ) source
         WHERE operation.id = source.operation_id
        """
    )

    cr.execute(
        """
        UPDATE sn_wsd_process_route_operation route_operation
           SET x_allow_repair_return = source.allow_repair_return
          FROM (
                SELECT current_route_operation_id, bool_or(legacy_allow_repair_return) AS allow_repair_return
                  FROM sn_wsd_mrp_migration_workcenter
                 WHERE current_route_operation_id IS NOT NULL
                 GROUP BY current_route_operation_id
               ) source
         WHERE route_operation.id = source.current_route_operation_id
        """
    )

    cr.execute(
        """
        UPDATE mrp_routing_workcenter bom_operation
           SET x_allow_repair_return = route_operation.x_allow_repair_return
          FROM sn_wsd_process_route_operation route_operation
         WHERE bom_operation.x_route_operation_id = route_operation.id
        """
    )

    cr.execute(
        """
        INSERT INTO sn_wsd_process_route_operation_rel (operation_id, blocked_by_id)
        SELECT current_route_operation_id, previous_route_operation_id
          FROM sn_wsd_mrp_migration_workcenter
         WHERE current_route_operation_id IS NOT NULL
           AND previous_route_operation_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    cr.execute('DROP TABLE IF EXISTS sn_wsd_mrp_migration_workcenter')

    _logger.info('Completed SN WSD MRP 19.0.3.5.7 master-data migration.')
