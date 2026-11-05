import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Create the not stored return operation on existing warehouses.

    The receipt and quality control transfers of a multi-step reception do not
    manage lots, so returning their goods requires an operation that does not
    require a batch either. The operation type is created by the standard
    warehouse machinery, which is triggered here for the warehouses that
    already exist.

    The barcode module, loaded after this one, adds required columns to the
    operation types: creating an operation type before it is loaded would
    violate those constraints. In that case the operation type is created on
    first use instead (see ``_ensure_unstored_return_type``).
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'restrict_put_in_pack' not in env['stock.picking.type']._fields:
        _logger.info(
            "sn_wsd_stock: not stored return operation deferred to first use")
        return
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    for warehouse in warehouses:
        picking_type_values = (
            warehouse._create_or_update_sequences_and_picking_types())
        if picking_type_values:
            warehouse.write(picking_type_values)
    _logger.info(
        "sn_wsd_stock: not stored return operation set up on %s warehouse(s)",
        len(warehouses))
