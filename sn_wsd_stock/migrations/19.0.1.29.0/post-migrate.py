import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Link the outsourcing issue operation and create the consignment one.

    The outsourcing issue operation was created by hand, so it carries no
    link on the warehouse: it is matched on its sequence code, the same way
    the issue label report recognizes it. The consignment receipt operation
    is new and is created through the standard warehouse hook, which writes
    the columns the barcode module adds to the operation types; a database
    without that module creates it on first use instead, because creating one
    during this upgrade would violate those required columns.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    PickingType = env['stock.picking.type'].with_context(active_test=False)
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    for warehouse in warehouses:
        if warehouse.sn_outsourcing_issue_type_id:
            continue
        picking_type = PickingType.search([
            ('sequence_code', '=', 'RES'),
            ('code', '=', 'internal'),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        if picking_type:
            warehouse.sn_outsourcing_issue_type_id = picking_type.id
    env['stock.move'].with_context(active_test=False).search(
        [])._compute_sn_operation_kind()
    if 'restrict_put_in_pack' not in env['stock.picking.type']._fields:
        _logger.info(
            'sn_wsd_stock: consignment receipt deferred to its first use')
        return
    for warehouse in warehouses:
        values = warehouse._create_or_update_sequences_and_picking_types()
        if values:
            warehouse.write(values)
