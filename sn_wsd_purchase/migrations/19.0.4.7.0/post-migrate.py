from odoo import SUPERUSER_ID, api

BATCH_SIZE = 500


def migrate(cr, version):
    """Recompute the purchase status of the request lines.

    The received quantity is a dependency of the purchase status from this
    version on: until now the status was only computed when the purchase order
    changed, so the lines received in full kept the status of their order. They
    are recomputed here, batch by batch, so the stored values are the ones the
    computation gives.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['purchase.request.line']
    offset = 0
    while True:
        batch = lines.search([], offset=offset, limit=BATCH_SIZE)
        if not batch:
            break
        batch._compute_purchase_state()
        env.flush_all()
        offset += BATCH_SIZE
