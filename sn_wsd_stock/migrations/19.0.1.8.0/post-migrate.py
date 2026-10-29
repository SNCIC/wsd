import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MAX_UPSTREAM_DEPTH = 10


def _upstream_partners(env, picking):
    """Partners carried by the transfers this one was pushed from."""
    partners = env['res.partner']
    visited = set(picking.ids)
    moves = picking.move_ids
    for _depth in range(MAX_UPSTREAM_DEPTH):
        upstream_pickings = moves.move_orig_ids.picking_id
        new_pickings = upstream_pickings.filtered(
            lambda upstream: upstream.id not in visited)
        if not new_pickings:
            break
        visited |= set(new_pickings.ids)
        partners |= new_pickings.partner_id
        moves = new_pickings.move_ids
    return partners


def migrate(cr, version):
    """Restore the contact of the quality control and storage transfers.

    The push rules used to build the downstream transfers of a three-step
    receipt without the contact of the transfer they come from, so the quality
    control transfer (and the inspection record reading its supplier from it)
    and the storage transfer were left blank. The push rule carries the
    contact now; this fills the transfers created before.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    warehouses = env['stock.warehouse'].search([])
    type_ids = (warehouses.mapped('qc_type_id')
                | warehouses.mapped('store_type_id')).ids
    if not type_ids:
        return

    pickings = env['stock.picking'].search([
        ('picking_type_id', 'in', type_ids),
        ('partner_id', '=', False),
    ])
    filled = 0
    for picking in pickings:
        partners = _upstream_partners(env, picking)
        if len(partners) != 1:
            continue  # ambiguous (several suppliers merged): leave it empty
        picking.with_context(sn_skip_picking_partner_audit=True).write(
            {'partner_id': partners.id})
        filled += 1

    _logger.info(
        "sn_wsd_stock: contact restored on %s of %s downstream transfer(s)",
        filled, len(pickings))
