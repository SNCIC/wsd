from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Default the other operations on the inventory adjustment location."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    warehouses._create_or_update_sequences_and_picking_types()
