# -*- coding: utf-8 -*-
"""Pre-migration for 19.0.5.0.0 — switch the route to the standalone
confirmation lifecycle (single record per company+code).

Runs before Odoo rewrites the schema/views:
- drop the old unique(company_id, code, version) constraint
- cast the ``version`` column from varchar to integer ('1.0' -> 1)
- add ``state`` / ``confirmed_by`` / ``confirmed_date`` from the PLM fields
- deactivate the obsolete sn_wsd_plm inherited route view (its xpath targets
  a button that no longer exists)
"""


def migrate(cr, version):
    # 1. Drop the old multi-record unique constraint (keep others intact).
    cr.execute("""
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'sn_wsd_process_route'::regclass
          AND contype = 'u'
          AND pg_get_constraintdef(oid) ILIKE '%version%'
    """)
    for (conname,) in cr.fetchall():
        cr.execute("ALTER TABLE sn_wsd_process_route DROP CONSTRAINT IF EXISTS %s" % conname)

    # 2. version: varchar ('1.0') -> integer
    cr.execute(r"""
        ALTER TABLE sn_wsd_process_route
        ALTER COLUMN version TYPE integer
        USING COALESCE(NULLIF(regexp_replace(version, '\..*$', ''), '')::int, 0)
    """)

    # 3. state / confirmation fields from the PLM columns
    cr.execute("ALTER TABLE sn_wsd_process_route ADD COLUMN IF NOT EXISTS state varchar")
    cr.execute("""
        UPDATE sn_wsd_process_route SET state = CASE COALESCE(x_plm_state, 'draft')
            WHEN 'released' THEN 'confirmed'
            WHEN 'review' THEN 'draft'
            WHEN 'obsolete' THEN 'cancelled'
            WHEN 'cancelled' THEN 'cancelled'
            ELSE 'draft'
        END
    """)
    cr.execute("UPDATE sn_wsd_process_route SET state = 'draft' WHERE state IS NULL")
    cr.execute("ALTER TABLE sn_wsd_process_route ALTER COLUMN state SET NOT NULL")
    cr.execute("ALTER TABLE sn_wsd_process_route ADD COLUMN IF NOT EXISTS confirmed_by int4")
    cr.execute("ALTER TABLE sn_wsd_process_route ADD COLUMN IF NOT EXISTS confirmed_date timestamp")
    cr.execute("""
        UPDATE sn_wsd_process_route SET confirmed_by = x_released_by
        WHERE x_released_by IS NOT NULL AND state = 'confirmed'
    """)
    cr.execute("""
        UPDATE sn_wsd_process_route SET confirmed_date = x_released_date
        WHERE x_released_date IS NOT NULL AND state = 'confirmed'
    """)

    # 4. Deactivate the removed sn_wsd_plm inherited view on the route form:
    #    its xpath points at a button that no longer exists.
    cr.execute("""
        UPDATE ir_ui_view SET active = false
        WHERE model = 'sn.wsd.process.route'
          AND id IN (
              SELECT res_id FROM ir_model_data
              WHERE module = 'sn_wsd_plm' AND model = 'ir.ui.view'
          )
    """)
