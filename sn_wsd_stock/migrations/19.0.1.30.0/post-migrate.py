import logging

from babel.messages.pofile import read_po

from odoo import SUPERUSER_ID, api
from odoo.tools.misc import file_path

_logger = logging.getLogger(__name__)

# Inventory operations the warehouse carries and the English name of the
# virtual location each of them ends on. The name of a location is not
# translatable: it is written in the language of the administrator creating it,
# so the migration renames the locations it creates with the translated name of
# the po file instead of writing it in the source, like the barcode module does
# with the names of the operation types.
INVENTORY_OPERATIONS = (('loss', 'Inventory Loss'), ('gain', 'Inventory Gain'))


def _load_location_names():
    """Translated names of the two inventory operation locations."""
    try:
        path = file_path('sn_wsd_stock/i18n/zh_CN.po')
    except FileNotFoundError:
        return {}
    with open(path, 'rb') as handle:
        catalog = read_po(handle, locale='zh_CN')
    names = {}
    for _kind, msgid in INVENTORY_OPERATIONS:
        message = catalog.get(msgid)
        if message is not None and message.string:
            names[msgid] = message.string
    return names


def migrate(cr, version):
    """Create or link the inventory loss and gain operations.

    The two virtual locations are created first: they carry no column added by
    another module, so they can be created during this upgrade. The operation
    types are created through the standard warehouse hook, which writes the
    columns the barcode module adds to them; a database without that module
    creates them on first use instead, because creating one during this
    upgrade would violate those required columns.

    An operation created by hand before the upgrade is matched on its sequence
    code and linked to its warehouse first, so the standard machinery updates
    it instead of creating a second one. The kind of the stock moves is read on
    the operation type of their transfer, so the moves already stored are
    recomputed once the operations are in place.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    PickingType = env['stock.picking.type'].with_context(active_test=False)
    Location = env['stock.location'].with_context(active_test=False)
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    names = _load_location_names()
    chinese = bool(env['res.lang'].search_count([
        ('code', '=', 'zh_CN'),
        ('active', '=', True),
    ]))
    for warehouse in warehouses:
        for kind, msgid in INVENTORY_OPERATIONS:
            location = Location._sn_get_inventory_operation_location(
                kind, warehouse.company_id)
            name = names.get(msgid) if chinese else None
            if name and location.name != name:
                location.write({'name': name})
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
