# -*- coding: utf-8 -*-
"""Split the single report quantity into the three counters: legacy rows
carry OK-only amounts."""


def migrate(cr, version):
    cr.execute("""
        UPDATE sn_wsd_mes_operation_report
        SET qty_ok = COALESCE(qty_ok, 0) + COALESCE(qty, 0)
        WHERE qty IS NOT NULL AND qty > 0
          AND COALESCE(qty_ok, 0) = 0
    """)
    # the stored per-operation/order counters were computed from the old
    # column before the backfill ran -- recompute them from the new ones
    from odoo.api import Environment
    from odoo import SUPERUSER_ID
    env = Environment(cr, SUPERUSER_ID, {})
    RouteOp = env['sn.wsd.mes.order.route.operation']
    ops = RouteOp.search([])
    for fname in ('x_reported_qty', 'x_reported_ok_qty',
                  'x_reported_ng_qty', 'x_reported_scrap_qty', 'x_yield_rate'):
        env.add_to_compute(RouteOp._fields[fname], ops)
    Order = env['sn.wsd.mes.order']
    orders = Order.search([])
    for fname in ('x_input_qty', 'x_output_qty',
                  'x_workorder_input_qty', 'produced_qty'):
        env.add_to_compute(Order._fields[fname], orders)
    env.flush_all()
