from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Refresh the line-side replenishment rules of every workshop store.

    The rules now carry ``location_dest_from_rule``: without it the generated
    move takes the operation type destination (stock -> stock for an internal
    transfer) instead of the workshop store, so the material never reached the
    line and the follow-up manufacture / purchase rule was never triggered.
    Re-running the derivation updates the rules created by 19.0.14.14.0.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    workshops = env['sn.mrp.workshop'].search([('component_location_id', '!=', False)])
    workshops._ensure_line_side_replenishment()
