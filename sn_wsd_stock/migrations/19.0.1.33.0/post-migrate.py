import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Inventory loss and gain operations of the former feature, and the sequence
# code they were created with.
LEGACY_OPERATIONS = (
    ('IVL', 'loss'),
    ('IVG', 'gain'),
)
# Columns the warehouse linked its two inventory operation types on. They are
# removed from the model, but the database keeps them and they are the only
# record of the operation each warehouse used.
LEGACY_TYPE_COLUMNS = (
    'sn_inventory_loss_type_id',
    'sn_inventory_gain_type_id',
)


def _get_legacy_types(cr, env):
    """Operation types the former inventory operation menus used."""
    PickingType = env['stock.picking.type'].with_context(active_test=False)
    cr.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'stock_warehouse'
        """,
    )
    columns = {row[0] for row in cr.fetchall()} & set(LEGACY_TYPE_COLUMNS)
    type_ids = set()
    for column in LEGACY_TYPE_COLUMNS:
        if column not in columns:
            continue
        cr.execute(
            f'SELECT {column} FROM stock_warehouse WHERE {column} IS NOT NULL')
        type_ids.update(row[0] for row in cr.fetchall())
    types = PickingType.browse(sorted(type_ids))
    for sequence_code, _kind in LEGACY_OPERATIONS:
        types |= PickingType.search([('sequence_code', '=', sequence_code)])
    return types.exists()


def _mark_legacy_pickings(cr, types):
    """Keep the marker the inventory detail lines are read on.

    The kind of a move was read on the operation type of its transfer. The
    types are retired here, so the transfers keep the kind they were booked
    with on their own marker, which the stock move computation reads as a
    fallback.
    """
    kinds = dict(LEGACY_OPERATIONS)
    for picking_type in types:
        kind = kinds.get(picking_type.sequence_code)
        if not kind:
            continue
        cr.execute(
            """
            UPDATE stock_picking
               SET sn_inventory_operation = %s
             WHERE picking_type_id = %s
               AND sn_inventory_operation IS NULL
            """,
            (kind, picking_type.id),
        )


def migrate(cr, version):
    """Retire the inventory loss and gain operation types.

    The inventory losses and gains are no longer documents of their own: the
    difference of a counting is booked by the physical inventory of the stock
    module, on stock moves carrying the inventory location of the product, and
    the inventory loss and gain detail reports list those moves. The two
    operation types are therefore retired, together with their menus.

    The transfers created by the former feature are kept: they are the history
    of the stock and of its valuation. They keep the marker their detail lines
    are read on, their operation types are archived (or removed when no
    transfer ever used them), and the kind of their moves is recomputed, as is
    the kind of the inventory moves already booked by the physical inventory.

    The operation types are read on the removed warehouse columns with SQL: the
    model no longer knows them, and matching on the sequence code alone cannot
    tell which warehouse each type belongs to on a database with several
    warehouses.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    types = _get_legacy_types(cr, env)
    if not types:
        _logger.info('sn_wsd_stock: no inventory operation type to retire')
        return
    _mark_legacy_pickings(cr, types)
    env.invalidate_all()
    env.flush_all()

    moves = env['stock.move'].search([('is_inventory', '=', True)])
    moves |= env['stock.move'].search([('picking_type_id', 'in', types.ids)])
    if moves:
        moves._compute_sn_operation_kind()

    PickingType = env['stock.picking.type'].with_context(active_test=False)
    Move = env['stock.move'].with_context(active_test=False)
    Picking = env['stock.picking'].with_context(active_test=False)
    for picking_type in types:
        used = (
            Picking.search_count([('picking_type_id', '=', picking_type.id)])
            or Move.search_count([('picking_type_id', '=', picking_type.id)])
        )
        sequence = picking_type.sequence_id
        try:
            with cr.savepoint():
                if used:
                    picking_type.write({'active': False})
                else:
                    picking_type.unlink()
                if sequence and not PickingType.search_count(
                        [('sequence_id', '=', sequence.id)]):
                    sequence.write({'active': False})
        except Exception:  # noqa: BLE001 - a transfer always wins over cleanup
            _logger.warning(
                'sn_wsd_stock: could not retire the inventory operation type %s',
                picking_type.display_name, exc_info=True)
            picking_type.write({'active': False})
    open_pickings = Picking.search_count([
        ('sn_inventory_operation', '!=', False),
        ('state', 'not in', ('done', 'cancel')),
    ])
    if open_pickings:
        _logger.warning(
            'sn_wsd_stock: %s inventory loss or gain transfers are still open',
            open_pickings)
