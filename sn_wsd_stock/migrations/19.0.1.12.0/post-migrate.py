import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Stop the pre-putaway transfers from requiring a lot.

    The internal batches are generated at putaway now, so the receipt and the
    quality control transfer of a multi-step reception must accept tracked
    goods without a lot. Both lot options are cleared on their operation
    types, which is how Odoo knows an operation does not manage lots; the
    storage transfer keeps its existing lots so the generated batches are
    used there.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    multi_step = warehouses.filtered(
        lambda warehouse: warehouse.reception_steps != 'one_step')
    picking_types = (
        multi_step.mapped('in_type_id') | multi_step.mapped('qc_type_id')
    )
    if not picking_types:
        return
    picking_types.write({
        'use_create_lots': False,
        'use_existing_lots': False,
    })
    _logger.info(
        "sn_wsd_stock: lot requirement cleared on %s pre-putaway operation(s)",
        len(picking_types))
