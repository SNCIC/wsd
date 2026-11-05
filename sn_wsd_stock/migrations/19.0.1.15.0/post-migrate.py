import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Rename the vendor return operation.

    The operation now also returns the goods that are already stored, so it is
    no longer qualified as "not stored". The operation types created by the
    previous version are renamed; a missing one is created on first use with
    the new name.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    picking_types = warehouses.mapped('sn_unstored_return_type_id')
    if not picking_types:
        return
    picking_types.write({'name': env._('Return to Vendor')})
    for warehouse in warehouses:
        picking_type = warehouse.sn_unstored_return_type_id
        if picking_type.sequence_id and picking_type.sequence_id.name != env._(
                '%(name)s Sequence vendor return', name=warehouse.name):
            picking_type.sequence_id.write({
                'name': env._(
                    '%(name)s Sequence vendor return', name=warehouse.name),
            })
    _logger.info(
        "sn_wsd_stock: vendor return operation renamed on %s warehouse(s)",
        len(warehouses))
