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
            route.route_flow_json = json.dumps(graph)
            migrated_json += 1
    _logger.info("route_flow_json: migrated %d route(s)", migrated_json)

    migrated_draw = 0
    for route in routes:
        drawing_no = (route.x_drawing_no or '').strip()
        if not drawing_no:
            continue
        already = Drawing.search_count([
            ('route_id', '=', route.id), ('x_drawing_no', '=', drawing_no),
        ])
        if not already:
            Drawing.create({'route_id': route.id, 'x_drawing_no': drawing_no})
            migrated_draw += 1
    _logger.info("route drawings: migrated %d binding(s)", migrated_draw)
