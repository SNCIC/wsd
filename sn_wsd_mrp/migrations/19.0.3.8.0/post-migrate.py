import json
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """One-time migration to the JSON-backed common route template.

    1. Materialise existing relational operations (sn.wsd.process.route.operation
       + DAG) into ``route_flow_json`` so the flow editor keeps showing them.
    2. Copy each route's legacy single ``x_drawing_no`` into a
       ``sn.wsd.process.route.drawing`` binding (so the resolver keeps working
       through the binding table).
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Route = env['sn.wsd.process.route']
    Drawing = env['sn.wsd.process.route.drawing']

    routes = Route.search([])
    migrated_json = 0
    for route in routes:
        if route.route_flow_json:
            continue
        graph = route._flow_graph_from_operations()
        if graph.get('nodes'):
            cr.execute(
                "UPDATE sn_wsd_process_route SET route_flow_json = %s WHERE id = %s",
                (json.dumps(graph), route.id),
            )
            migrated_json += 1
    _logger.info("route_flow_json: migrated %d route(s)", migrated_json)

    migrated_draw = 0
    # The legacy column only exists on databases that already ran a version
    # defining it; probe it in SQL instead of the ORM (the field is gone
    # from the model in this version).
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'sn_wsd_process_route' "
        "AND column_name = 'x_drawing_no'")
    legacy_drawings = {}
    if cr.fetchone():
        cr.execute(
            "SELECT id, x_drawing_no FROM sn_wsd_process_route "
            "WHERE x_drawing_no IS NOT NULL AND x_drawing_no <> ''")
        legacy_drawings = {
            route_id: drawing_no.strip()
            for route_id, drawing_no in cr.fetchall()
            if drawing_no.strip()
        }
    for route_id, drawing_no in legacy_drawings.items():
        already = Drawing.search_count([
            ('route_id', '=', route_id), ('x_drawing_no', '=', drawing_no),
        ])
        if not already:
            Drawing.create({'route_id': route_id, 'x_drawing_no': drawing_no})
            migrated_draw += 1
    _logger.info("route drawings: migrated %d binding(s)", migrated_draw)
