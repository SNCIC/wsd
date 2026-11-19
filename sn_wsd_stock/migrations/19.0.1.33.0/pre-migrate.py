import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Fields the former inventory loss and gain feature carried and no module
# defines any more.
REMOVED_FIELD_NAMES = (
    'sn_inventory_location_id',
    'sn_inventory_loss_type_id',
    'sn_inventory_gain_type_id',
)


def migrate(cr, version):
    """Drop the views still reading the removed inventory operation fields.

    The inventory losses and gains no longer have their own operation types,
    and the valuation location of the former documents is gone with them. The
    views are removed from the module data with this version, but Odoo only
    deletes the records that disappear from the files at the end of the
    upgrade, once every view has been loaded and validated: an inherited view
    still stored in the database would break the validation of the stock
    transfer form, and of every view inheriting it, before that cleanup runs.

    The views are read on the fields they name, not on their external
    identifiers: the feature went through several view layouts, and a view
    written by hand inheriting one of them carries the same fields.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    View = env['ir.ui.view'].with_context(active_test=False)
    views = View
    for field_name in REMOVED_FIELD_NAMES:
        cr.execute(
            "SELECT id FROM ir_ui_view WHERE arch_db::text LIKE %s",
            ('%' + field_name + '%',),
        )
        views |= View.browse([row[0] for row in cr.fetchall()])
    if views:
        _logger.info(
            'sn_wsd_stock: removing %s views reading the retired inventory '
            'operation fields: %s',
            len(views), ', '.join(views.mapped('name')))
        views.unlink()
