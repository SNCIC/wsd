from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Create the other receipt and delivery operations of the warehouses.

    This module adds required columns to the operation types and is the first
    one loaded after sn_wsd_stock that knows them, so the operations the
    stock module could not create during its own upgrade are created here.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    # the core method requires a singleton: one call per warehouse
    for warehouse in warehouses:
        warehouse._create_or_update_sequences_and_picking_types()
