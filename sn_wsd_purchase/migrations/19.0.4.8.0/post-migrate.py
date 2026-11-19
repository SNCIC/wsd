from odoo import SUPERUSER_ID, api

BATCH_SIZE = 500


def migrate(cr, version):
    """Recompute the statuses that compare the request line with its quantity.

    The quantity ordered for a request line is now the quantity of the purchase
    order lines split between the request lines sharing them, instead of the
    whole quantity of each order line. The purchase status and the receipt
    status both compare the line with that quantity, so the stored values are
    recomputed here, batch by batch.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['purchase.request.line']
    offset = 0
    while True:
        batch = lines.search([], offset=offset, limit=BATCH_SIZE)
        if not batch:
            break
        batch._compute_purchase_state()
        batch._compute_receipt_status()
        env.flush_all()
        offset += BATCH_SIZE
