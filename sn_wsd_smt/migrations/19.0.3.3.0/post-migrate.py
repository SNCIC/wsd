import odoo
from odoo.api import Environment


def migrate(cr, version):
    # Legacy single channel_sn column -> channel rows; feeders without a
    # legacy channel SN get one row keyed by feeder_sn so the
    # channel-count constraint holds for existing records.
    cr.execute("""
        SELECT id, company_id, feeder_sn, channel_sn
        FROM sn_smt_feeder
        WHERE channel_sn IS NULL OR channel_sn = ''
    """)
    missing = cr.fetchall()
    for feeder_id, company_id, feeder_sn, _legacy in missing:
        cr.execute(
            "INSERT INTO sn_smt_feeder_channel (feeder_id, channel_no, channel_sn, company_id)"
            " VALUES (%s, 1, %s, %s)",
            (feeder_id, feeder_sn, company_id),
        )

    cr.execute("""
        SELECT id, company_id, channel_sn FROM sn_smt_feeder
        WHERE channel_sn IS NOT NULL AND channel_sn <> ''
    """)
    legacy = cr.fetchall()
    seen = set()
    for feeder_id, company_id, channel_sn in legacy:
        key = (company_id, channel_sn)
        if key in seen:
            raise ValueError(
                'Duplicate legacy channel SN per company, fix before upgrade: %s' % channel_sn
            )
        seen.add(key)
        cr.execute(
            "INSERT INTO sn_smt_feeder_channel (feeder_id, channel_no, channel_sn, company_id)"
            " VALUES (%s, 1, %s, %s)",
            (feeder_id, channel_sn, company_id),
        )

    env = Environment(cr, odoo.SUPERUSER_ID, {})
    feeders = env['sn.smt.feeder'].search([])
    env.add_to_compute(feeders._fields['care_state'], feeders)
    env.flush_all()
