from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Link and create the other receipt and delivery operations.

    The operations were first carried by a module of their own; its operation
    types stay in the database when that module is uninstalled, so the
    warehouse links are restored from the sequence codes before the missing
    ones are created.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    PickingType = env['stock.picking.type'].with_context(active_test=False)
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    for code, field_name in (('OIN', 'other_in_type_id'), ('OOUT', 'other_out_type_id')):
        for warehouse in warehouses:
            if warehouse[field_name]:
                continue
            picking_type = PickingType.search([
                ('sequence_code', '=', code),
                ('warehouse_id', '=', warehouse.id),
            ], limit=1)
            if picking_type:
                warehouse[field_name] = picking_type.id
    warehouses._create_or_update_sequences_and_picking_types()
