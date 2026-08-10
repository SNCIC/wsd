import logging


_logger = logging.getLogger(__name__)


def _column_exists(cr, table_name, column_name):
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = %s
               AND column_name = %s
        )
        """,
        (table_name, column_name),
    )
    return cr.fetchone()[0]


def migrate(cr, version):
    if not version:
        return

    cr.execute('DROP TABLE IF EXISTS sn_wsd_mrp_migration_workcenter')
    cr.execute(
        """
        CREATE TABLE sn_wsd_mrp_migration_workcenter (
            operation_id integer,
            legacy_workcenter_id integer,
            legacy_station_type varchar,
            legacy_allow_repair_return boolean,
            current_route_operation_id integer,
            previous_route_operation_id integer
        )
        """
    )

    if _column_exists(cr, 'sn_wsd_operation', 'workcenter_id'):
        cr.execute(
            """
            INSERT INTO sn_wsd_mrp_migration_workcenter (operation_id, legacy_workcenter_id)
            SELECT id, workcenter_id
              FROM sn_wsd_operation
             WHERE workcenter_id IS NOT NULL
            """
        )

    if _column_exists(cr, 'mrp_workcenter', 'x_station_type'):
        cr.execute(
            """
            INSERT INTO sn_wsd_mrp_migration_workcenter (
                operation_id,
                legacy_workcenter_id,
                legacy_station_type
            )
            SELECT route_operation.operation_id, workcenter.id, workcenter.x_station_type
              FROM mrp_routing_workcenter bom_operation
              JOIN sn_wsd_process_route_operation route_operation
                ON route_operation.id = bom_operation.x_route_operation_id
              JOIN mrp_workcenter workcenter
                ON workcenter.id = bom_operation.workcenter_id
             WHERE workcenter.x_station_type IS NOT NULL
               AND route_operation.operation_id IS NOT NULL
            """
        )

        cr.execute(
            """
            INSERT INTO sn_wsd_mrp_migration_workcenter (
                operation_id,
                legacy_workcenter_id,
                legacy_station_type
            )
            SELECT operation.id, workcenter.id, workcenter.x_station_type
              FROM sn_wsd_operation operation
              JOIN mrp_workcenter workcenter
                ON workcenter.id = operation.workcenter_id
             WHERE workcenter.x_station_type IS NOT NULL
               AND operation.workcenter_id IS NOT NULL
            """
        )

    if _column_exists(cr, 'mrp_workcenter', 'x_allow_repair_return'):
        cr.execute(
            """
            INSERT INTO sn_wsd_mrp_migration_workcenter (
                current_route_operation_id,
                legacy_workcenter_id,
                legacy_allow_repair_return
            )
            SELECT route_operation.id, workcenter.id, workcenter.x_allow_repair_return
              FROM mrp_routing_workcenter bom_operation
              JOIN sn_wsd_process_route_operation route_operation
                ON route_operation.id = bom_operation.x_route_operation_id
              JOIN mrp_workcenter workcenter
                ON workcenter.id = bom_operation.workcenter_id
             WHERE workcenter.x_allow_repair_return IS NOT NULL
            """
        )

    if _column_exists(cr, 'mrp_workcenter', 'x_previous_workcenter_id'):
        cr.execute(
            """
            INSERT INTO sn_wsd_mrp_migration_workcenter (
                legacy_workcenter_id,
                current_route_operation_id,
                previous_route_operation_id
            )
            SELECT current_workcenter.id, current_bom.x_route_operation_id, previous_bom.x_route_operation_id
              FROM mrp_workcenter current_workcenter
              JOIN mrp_workcenter previous_workcenter
                ON previous_workcenter.id = current_workcenter.x_previous_workcenter_id
              JOIN mrp_routing_workcenter current_bom
                ON current_bom.workcenter_id = current_workcenter.id
              JOIN mrp_routing_workcenter previous_bom
                ON previous_bom.bom_id = current_bom.bom_id
               AND previous_bom.workcenter_id = previous_workcenter.id
             WHERE current_workcenter.x_previous_workcenter_id IS NOT NULL
               AND current_bom.x_route_operation_id IS NOT NULL
               AND previous_bom.x_route_operation_id IS NOT NULL
               AND current_bom.x_route_operation_id != previous_bom.x_route_operation_id
            """
        )

    _logger.info('Prepared SN WSD MRP 19.0.3.5.7 master-data migration.')
