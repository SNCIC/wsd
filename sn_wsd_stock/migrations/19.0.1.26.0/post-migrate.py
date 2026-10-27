from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Preset the other operation types and fix the default locations.

    The virtual locations of the other operations already exist in a database
    that carried them: they are matched on their name, so the preset types are
    linked to them. The other operations are put back on the inventory
    adjustment location, which the previous lookup on the ``inventory`` usage
    could miss as soon as the virtual locations existed.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'sn.wsd.stock.other.operation.type' not in env:
        return
    env['sn.wsd.stock.other.operation.type']._ensure_default_types()
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    warehouses._create_or_update_sequences_and_picking_types()
