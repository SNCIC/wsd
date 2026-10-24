import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Link and create the other receipt and delivery operations.

    The operations were first carried by a module of their own; its operation
    types stay in the database when that module is uninstalled, so the
    warehouse links are restored from the sequence codes.

    The barcode module adds required columns to the operation types and is
    loaded after this module: creating an operation type here would violate
    those constraints. The missing operations are created from the barcode
    module instead.
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
    if 'restrict_put_in_pack' not in env['stock.picking.type']._fields:
        _logger.info(
            'sn_wsd_stock: other operations deferred to the barcode module')
        return
    warehouses._create_or_update_sequences_and_picking_types()
