# -*- coding: utf-8 -*-
"""Backfill the manual start flag from the legacy computed is_input column."""

from odoo.tools import sql


def migrate(cr, version):
    if sql.table_exists(cr, 'sn_wsd_mes_order_route_operation'):
        cr.execute("""
            UPDATE sn_wsd_mes_order_route_operation
            SET x_allow_entry = TRUE, is_input = TRUE
            WHERE is_input AND NOT x_allow_entry
        """)
