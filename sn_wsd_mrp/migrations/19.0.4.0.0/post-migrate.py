import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Drop retired daily-plan models and the FK columns they left behind.

    The PRD v1 rebuild replaces the mixed ``sn.wsd.daily.production.order`` /
    ``sn.wsd.daily.route.operation`` models with a single ``sn.wsd.mes.order``.
    Odoo's own schema sync usually drops removed columns, but the mes DB may
    carry stale state, so be explicit.
    """
    if not version:
        return

    cr.execute("DROP TABLE IF EXISTS sn_wsd_daily_route_operation_rel CASCADE")
    cr.execute("DROP TABLE IF EXISTS sn_wsd_daily_route_operation CASCADE")
    cr.execute("DROP TABLE IF EXISTS sn_wsd_daily_production_order CASCADE")

    for table, column in (
        ('sn_wsd_mes_sn_travel', 'daily_order_id'),
        ('sn_wsd_mes_sn_travel', 'daily_route_operation_id'),
        ('sn_wsd_internal_serial', 'current_daily_order_id'),
    ):
        cr.execute("ALTER TABLE %s DROP COLUMN IF EXISTS %s" % (table, column))

    for column in ('x_daily_order_count', 'x_split_state', 'x_total_planned_qty', 'x_total_done_qty'):
        cr.execute("ALTER TABLE mrp_production DROP COLUMN IF EXISTS %s" % column)

    _logger.info("sn_wsd_mrp 19.0.4.0.0: dropped retired daily-plan schema")
