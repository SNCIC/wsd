"""Backfill ``serial_history_ids`` for station-mode settlements.

Before this version a settlement paid "one OK pass per SN" and stored only the
covered SNs. The口径 changed to "one pay per OK pass" (rework re-passes and
batch-pass rows included), so the coverage set moved from SNs to station-pass
records. Existing settlements must claim the passes they already paid,
otherwise those passes would show up as unsettled again and be paid twice.

Direct SQL on the relation table: confirmed settlements refuse ORM writes.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT id, qty_ok, mes_order_id, route_operation_id
        FROM sn_wsd_piece_settlement
        WHERE manage_mode = 'station'
          AND state != 'void'
          AND route_operation_id IS NOT NULL
        ORDER BY id
    """)
    settlements = cr.fetchall()

    # 已被任意一张单覆盖的过站记录，避免重复占用
    cr.execute("SELECT history_id FROM sn_wsd_piece_settlement_pass_rel")
    assigned = {row[0] for row in cr.fetchall()}

    backfilled = 0
    for settlement_id, qty_ok, order_id, operation_id in settlements:
        if not order_id:
            continue
        cr.execute("""
            SELECT history_id
            FROM sn_wsd_piece_settlement_pass_rel
            WHERE settlement_id = %s
        """, (settlement_id,))
        if cr.fetchall():
            continue
        cr.execute("""
            SELECT h.id
            FROM sn_wsd_serial_operation_history h
            JOIN sn_wsd_piece_settlement_serial_rel r
              ON r.serial_identity_id = h.serial_identity_id
             AND r.settlement_id = %s
            WHERE h.mes_order_id = %s
              AND h.route_operation_id = %s
              AND h.result = 'ok'
            ORDER BY h.out_date ASC NULLS LAST, h.id ASC
        """, (settlement_id, order_id, operation_id))
        candidates = [row[0] for row in cr.fetchall() if row[0] not in assigned]
        limit = int(qty_ok or 0) or len(candidates)
        taken = candidates[:limit]
        if not taken:
            continue
        cr.execute("""
            INSERT INTO sn_wsd_piece_settlement_pass_rel (settlement_id, history_id)
            SELECT %s, unnest(%s::int[])
            ON CONFLICT DO NOTHING
        """, (settlement_id, taken))
        assigned |= set(taken)
        backfilled += 1

    _logger.info(
        'piece-rate: backfilled station-pass coverage for %s settlement(s)',
        backfilled)
