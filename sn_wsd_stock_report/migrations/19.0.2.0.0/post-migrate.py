from odoo import SUPERUSER_ID, api

BATCH_SIZE = 1000


def migrate(cr, version):
    """Fill the report location of the existing stock locations.

    A location is reported on the store it belongs to: the stores are the
    locations below the warehouse view location and below the stock area, and
    the storage slots (dash in the name) are reported on their stock area. The
    locations are walked from the top of the tree down, so the report location
    of a parent is known when its children are computed.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    locations = env['stock.location'].with_context(active_test=False)
    cr.execute("""
        SELECT id
          FROM stock_location
         WHERE usage = 'internal'
         ORDER BY length(parent_path), id
    """)
    location_ids = [row[0] for row in cr.fetchall()]
    for index in range(0, len(location_ids), BATCH_SIZE):
        chunk = location_ids[index:index + BATCH_SIZE]
        locations.browse(chunk)._compute_sn_report_location_id()
        env.flush_all()
