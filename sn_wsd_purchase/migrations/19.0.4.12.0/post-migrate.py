from odoo import SUPERUSER_ID, api

BATCH_SIZE = 500


def migrate(cr, version):
    """Recompute the pending quantity of the request lines.

    The quantity left to buy now reports zero on a business closed line, and
    the stored quantity of the module follows it: the stored values are
    recomputed here, batch by batch, so the "to buy" filters of the module
    agree with the closing.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['purchase.request.line']
    offset = 0
    while True:
        batch = lines.search([], offset=offset, limit=BATCH_SIZE)
        if not batch:
            break
        batch._compute_qty_to_buy()
        env.flush_all()
        offset += BATCH_SIZE
