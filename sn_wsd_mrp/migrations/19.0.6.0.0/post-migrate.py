import logging

from odoo.tools import sql

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Board-side scheduling (SMT 面别与工艺路线设计).

    1. Drop the retired per-drawing uniqueness constraint: matching is now
       per 车间 + 图号 + 面别, so uniqueness moved to (company, workshop,
       drawing, side) -- enforced by ``_drawing_side_route_uniq`` created by
       the regular schema sync.
    2. Backfill the stored binding side/workshop from its route (the related
       columns may lag behind the constraint creation during upgrade).
    3. All products default to the single board side (所有产品默认单面):
       existing NULL board sides become 'single', matching the field default.
    """
    if not version:
        return

    if sql.table_exists(cr, 'sn_wsd_process_route_drawing'):
        cr.execute("""
            ALTER TABLE sn_wsd_process_route_drawing
            DROP CONSTRAINT IF EXISTS sn_wsd_process_route_drawing_drawing_single_route
        """)
        if sql.table_exists(cr, 'sn_wsd_process_route'):
            cr.execute("""
                UPDATE sn_wsd_process_route_drawing d
                SET x_side = r.x_production_side,
                    x_workshop_id = r.x_workshop_id
                FROM sn_wsd_process_route r
                WHERE r.id = d.route_id
                  AND (d.x_side IS DISTINCT FROM r.x_production_side
                       OR d.x_workshop_id IS DISTINCT FROM r.x_workshop_id)
            """)
    if sql.table_exists(cr, 'product_template'):
        cr.execute("""
            UPDATE product_template
            SET x_board_side = 'single'
            WHERE x_board_side IS NULL
        """)

    _logger.info("sn_wsd_mrp 19.0.6.0.0: drawing bindings are now side-aware; "
                 "products default to the single board side")
