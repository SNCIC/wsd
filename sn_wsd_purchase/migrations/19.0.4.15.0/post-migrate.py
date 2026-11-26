from odoo import SUPERUSER_ID, api

BATCH_SIZE = 500


def migrate(cr, version):
    """Compute the stored ordered quantity of the request lines.

    The ordered quantity of the module was computed on the fly and is stored
    now, so the detail reports can be ordered and aggregated on it. The
    quantity is recomputed here, batch by batch, on the lines that already
    exist.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['purchase.request.line']
    offset = 0
    while True:
        batch = lines.search([], offset=offset, limit=BATCH_SIZE, order='id')
        if not batch:
            break
        batch._compute_purchased_qty()
        env.flush_all()
        offset += BATCH_SIZE
