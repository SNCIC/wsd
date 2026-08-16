# -*- coding: utf-8 -*-
"""Rename sn.wsd.mes.route -> sn.wsd.mes.order.route.

The old tables only ever held demo/E2E data (feature was never released), so
they are dropped and rebuilt. Orders that had a route lose it; online orders
without a route are meaningless and are removed (they were demo data)."""
from odoo.tools import sql


def migrate(cr, version):
    if not sql.table_exists(cr, 'sn_wsd_mes_order_route'):
        # execution records pointed at the old operation rows (test/demo data)
        cr.execute("DELETE FROM sn_wsd_serial_wip")
        cr.execute("DELETE FROM sn_wsd_serial_operation_history")
        cr.execute("DELETE FROM sn_wsd_mes_operation_report")
        cr.execute("DELETE FROM sn_wsd_mes_order WHERE x_online_date IS NOT NULL")
        cr.execute("UPDATE sn_wsd_mes_order SET x_mes_route_id = NULL")
        cr.execute("DROP TABLE IF EXISTS mes_route_operation_rel CASCADE")
        cr.execute("DROP TABLE IF EXISTS sn_wsd_mes_route_operation CASCADE")
        cr.execute("DROP TABLE IF EXISTS sn_wsd_mes_route CASCADE")
        # stale ir.model records for the old model names
        cr.execute("""
            DELETE FROM ir_model_data d USING ir_model m
            WHERE d.res_id = m.id AND d.model = 'ir.model'
              AND m.model IN ('sn.wsd.mes.route', 'sn.wsd.mes.route.operation')
        """)
        cr.execute("""
            DELETE FROM ir_model_access a USING ir_model m
            WHERE a.model_id = m.id
              AND m.model IN ('sn.wsd.mes.route', 'sn.wsd.mes.route.operation')
        """)
        cr.execute("""
            DELETE FROM ir_model_constraint c USING ir_model m
            WHERE c.model = m.id
              AND m.model IN ('sn.wsd.mes.route', 'sn.wsd.mes.route.operation')
        """)
        cr.execute("""
            DELETE FROM ir_model_fields f USING ir_model m
            WHERE f.model_id = m.id
              AND m.model IN ('sn.wsd.mes.route', 'sn.wsd.mes.route.operation')
        """)
        cr.execute("DELETE FROM ir_model WHERE model IN ('sn.wsd.mes.route', 'sn.wsd.mes.route.operation')")
