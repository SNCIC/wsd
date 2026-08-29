from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    request_lines = env["purchase.request.line"].search([])
    request_lines._compute_qty()
    request_lines._compute_qty_to_buy()
    request_lines.flush_recordset(
        ["qty_done", "qty_in_progress", "qty_to_buy", "pending_qty_to_receive"]
    )
