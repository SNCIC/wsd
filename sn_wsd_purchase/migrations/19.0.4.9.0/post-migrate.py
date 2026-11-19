from odoo import SUPERUSER_ID, api

BATCH_SIZE = 500


def migrate(cr, version):
    """Recompute the quantities that were counted once per reception step.

    The received quantity of a request line adds up the allocations of the
    move that receives the goods only, instead of the allocations of every
    move of the reception: the allocation copied onto the moves of a reception
    in several steps was counted twice, which reported more goods received
    than ordered. The stored quantities and the values comparing them are
    recomputed here, batch by batch.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['purchase.request.line']
    offset = 0
    while True:
        batch = lines.search([], offset=offset, limit=BATCH_SIZE)
        if not batch:
            break
        batch._compute_qty()
        batch._compute_qty_to_buy()
        batch._compute_receipt_status()
        env.flush_all()
        offset += BATCH_SIZE
