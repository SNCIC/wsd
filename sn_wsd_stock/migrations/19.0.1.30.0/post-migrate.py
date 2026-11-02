import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Create or link the inventory loss and gain operations.

    The two operations are new: they are created through the standard
    warehouse hook, which writes the columns the barcode module adds to the
    operation types; a database without that module creates them on first use
    instead, because creating one during this upgrade would violate those
    required columns.

    An operation created by hand before the upgrade is matched on its sequence
    code and linked to its warehouse first, so the standard machinery updates
    it instead of creating a second one. The kind of the stock moves is read on
    the operation type of their transfer, so the moves already stored are
    recomputed once the operations are in place.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    PickingType = env['stock.picking.type'].with_context(active_test=False)
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    for code, field_name in (
            ('IVL', 'sn_inventory_loss_type_id'),
            ('IVG', 'sn_inventory_gain_type_id')):
        for warehouse in warehouses:
            if warehouse[field_name]:
                continue
            picking_type = PickingType.search([
                ('sequence_code', '=', code),
                ('warehouse_id', '=', warehouse.id),
            ], limit=1)
            if picking_type:
                warehouse[field_name] = picking_type.id
    env['stock.move'].with_context(active_test=False).search(
        [])._compute_sn_operation_kind()
    if 'restrict_put_in_pack' not in env['stock.picking.type']._fields:
        _logger.info(
            'sn_wsd_stock: inventory operation types deferred to their first use')
        return
    for warehouse in warehouses:
        values = warehouse._create_or_update_sequences_and_picking_types()
        if values:
            warehouse.write(values)
