from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Create or link the other receipt and delivery operations.

    This module adds required columns to the operation types and is the first
    one loaded after sn_wsd_stock that knows them, so the operations the stock
    module could not create during its own upgrade are created here.

    The operations created by a previous version of this script were not
    linked back to their warehouse (the values returned by the standard
    machinery were not written): they are linked first, so that the machinery
    updates them instead of creating a second pair.
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
    for warehouse in warehouses:
        picking_type_values = (
            warehouse._create_or_update_sequences_and_picking_types())
        if picking_type_values:
            warehouse.write(picking_type_values)
