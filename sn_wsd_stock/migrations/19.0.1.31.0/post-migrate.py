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
    through the standard warehouse hook, and the dedicated locations they no
    longer use are removed when they carry nothing.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    PickingType = env['stock.picking.type'].with_context(active_test=False)
    Location = env['stock.location'].with_context(active_test=False)
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    dedicated = Location
    for warehouse in warehouses:
        for field_name in (
                'sn_inventory_loss_type_id',
                'sn_inventory_gain_type_id'):
            picking_type = warehouse[field_name]
            if picking_type:
                dedicated |= (
                    picking_type.default_location_src_id
                    | picking_type.default_location_dest_id)
    for warehouse in warehouses:
        picking_type_values = (
            warehouse._create_or_update_sequences_and_picking_types())
        if picking_type_values:
            warehouse.write(picking_type_values)
    adjustment_locations = Location
    for warehouse in warehouses:
        adjustment_locations |= warehouse._get_inventory_adjustment_location()
    names = _load_location_names()
    for location in dedicated - adjustment_locations:
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
