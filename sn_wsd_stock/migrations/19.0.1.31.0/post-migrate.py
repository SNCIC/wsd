from babel.messages.pofile import read_po

from odoo import SUPERUSER_ID, api
from odoo.tools.misc import file_path

# English name of the dedicated locations the first version of the feature
# created, and the operation type field each of them was assigned to.
DEDICATED_LOCATION_NAMES = ('Inventory Loss', 'Inventory Gain')


def _load_location_names():
    """Names of the dedicated locations, in the language of the database.

    The name of a location is not translatable: the locations were created in
    the language of the administrator running the upgrade, so the translated
    names are read from the po file instead of being written in the source.
    """
    names = set(DEDICATED_LOCATION_NAMES)
    try:
        path = file_path('sn_wsd_stock/i18n/zh_CN.po')
    except FileNotFoundError:
        return names
    with open(path, 'rb') as handle:
        catalog = read_po(handle, locale='zh_CN')
    for msgid in DEDICATED_LOCATION_NAMES:
        message = catalog.get(msgid)
        if message is not None and message.string:
            names.add(message.string)
    return names


def migrate(cr, version):
    """Book the inventory loss and gain on the inventory adjustment location.

    The first version of the feature gave each operation its own inventory
    usage location. Every other inventory operation of the system, and the
    inventory adjustment of the products, goes through the inventory
    adjustment location of the company: the two operations are repointed there
    and the dedicated locations they no longer use are removed when they carry
    nothing.

    The operation types are updated in place and never created here: a
    database upgrading from the version that introduced them may not carry
    them yet, because the barcode module adds required columns to the
    operation types and is loaded after this module. That module's own
    migration creates them, on the inventory adjustment location. The
    locations are written directly for the same reason: the standard warehouse
    hook creates the missing operation types.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    PickingType = env['stock.picking.type'].with_context(active_test=False)
    Location = env['stock.location'].with_context(active_test=False)
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    customer_location = env.ref('stock.stock_location_customers')
    supplier_location = env.ref('stock.stock_location_suppliers')
    dedicated = Location
    for warehouse in warehouses:
        adjustment_location = warehouse._get_inventory_adjustment_location()
        loss_type = warehouse.sn_inventory_loss_type_id
        gain_type = warehouse.sn_inventory_gain_type_id
        for picking_type in loss_type | gain_type:
            dedicated |= (
                picking_type.default_location_src_id
                | picking_type.default_location_dest_id)
        if loss_type:
            loss_type.write({
                'default_location_src_id': warehouse.lot_stock_id.id,
                'default_location_dest_id': (
                    adjustment_location or customer_location).id,
            })
        if gain_type:
            gain_type.write({
                'default_location_src_id': (
                    adjustment_location or supplier_location).id,
                'default_location_dest_id': warehouse.lot_stock_id.id,
            })
    names = _load_location_names()
    for location in dedicated:
        if location.usage != 'inventory' or location.name not in names:
            continue
        used = (
            env['stock.quant'].search_count([('location_id', '=', location.id)])
            or env['stock.move'].search_count(
                ['|', ('location_id', '=', location.id),
                 ('location_dest_id', '=', location.id)])
            or env['stock.move.line'].search_count(
                ['|', ('location_id', '=', location.id),
                 ('location_dest_id', '=', location.id)])
            or env['stock.location'].search_count(
                [('location_id', '=', location.id)])
            or PickingType.search_count(
                ['|', ('default_location_src_id', '=', location.id),
                 ('default_location_dest_id', '=', location.id)])
        )
        if used:
            location.active = False
        else:
            location.unlink()
