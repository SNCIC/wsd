from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Default the other operations on the inventory adjustment location.

    The barcode module adds required columns to the operation types and is
    loaded after this module: updating them here would violate those
    constraints, the barcode module updates them when it is loaded.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'restrict_put_in_pack' not in env['stock.picking.type']._fields:
        return
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    warehouses._create_or_update_sequences_and_picking_types()
