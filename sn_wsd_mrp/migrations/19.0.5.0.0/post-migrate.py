# -*- coding: utf-8 -*-
"""Post-migration for 19.0.5.0.0 — collapse legacy multi-record revision
families into the single surviving route per (company, code).

Every former revision's flow JSON is archived as a version snapshot
(V1, V2, ...) on the surviving record; the other family members are
deactivated (归档), never deleted.
"""
from collections import defaultdict


def migrate(cr, version):
    cr.execute("SELECT id, company_id, code FROM sn_wsd_process_route")
    rows = cr.fetchall()
    families = defaultdict(list)
    for rid, comp, code in rows:
        families[(comp, code)].append(rid)

    for (comp, code), ids in families.items():
        # Newest released revision first, then the rest newest-first.
        cr.execute("""
            SELECT id, route_flow_json, x_released_by, x_released_date
            FROM sn_wsd_process_route
            WHERE id = ANY(%s)
            ORDER BY (x_plm_state = 'released') DESC,
                     x_released_date DESC NULLS LAST,
                     create_date DESC, id DESC
        """, (ids,))
        members = cr.fetchall()
        if not members:
            continue
        survivor = members[0][0]
        version_no = 0
        for _mid, json_txt, rel_by, rel_date in members:
            if not json_txt:
                continue
            version_no += 1
            cr.execute("""
                INSERT INTO sn_wsd_process_route_version
                    (route_id, company_id, version_no, route_flow_json,
                     confirmed_by, confirmed_date, create_uid, write_uid,
                     create_date, write_date)
                VALUES (%s, %s, %s, %s, %s, %s, 1, 1, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC')
            """, (survivor, comp, version_no, json_txt, rel_by, rel_date))
        cr.execute(
            "UPDATE sn_wsd_process_route SET version = %s, active = true WHERE id = %s",
            (version_no, survivor))
        others = [m[0] for m in members[1:]]
        if others:
            cr.execute(
                "UPDATE sn_wsd_process_route SET active = false WHERE id = ANY(%s)",
                (others,))
