from babel.messages.pofile import read_po

from odoo import SUPERUSER_ID, api
from odoo.tools.misc import file_path

# Operation types of the warehouse and the term their name is translated from.
OPERATIONS = (
    ('IVL', 'Inventory Losses'),
    ('IVG', 'Inventory Gains'),
)


def _load_names():
    """Names of the two operations, read from the stock module translations.

    The operations are created while the modules upgrade, before Odoo imports
    their translations, so their names are stored in English. The translated
    names are read from the po file instead of writing Chinese in the source.
    """
    try:
        path = file_path('sn_wsd_stock/i18n/zh_CN.po')
    except FileNotFoundError:
        return {}
    with open(path, 'rb') as handle:
        catalog = read_po(handle, locale='zh_CN')
    names = {}
    for _code, msgid in OPERATIONS:
        message = catalog.get(msgid)
        if message is not None and message.string:
            names[msgid] = message.string
    return names


def _translate_names(cr, names):
    for code, msgid in OPERATIONS:
        name = names.get(msgid)
        if not name:
            continue
        cr.execute(
            """
            UPDATE stock_picking_type
               SET name = jsonb_set(
                       COALESCE(name, '{}'::jsonb), '{zh_CN}', to_jsonb(%s::text))
             WHERE sequence_code = %s
            """,
            (name, code),
        )


def migrate(cr, version):
    """Create or link the inventory loss and gain operations.

    This module adds required columns to the operation types and is the first
    one loaded after sn_wsd_stock that knows them, so the operations the stock
    module could not create during its own upgrade are created here. An
    operation created by hand is matched on its sequence code and linked to its
    warehouse first, so the standard machinery updates it instead of creating a
    second one.

    The operations are created while the modules upgrade, before Odoo imports
    their translations: their names are booked in English and the translated
    names are written afterwards, on the language of the po file.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    PickingType = env['stock.picking.type'].with_context(active_test=False)
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
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
    for warehouse in warehouses:
        picking_type_values = (
            warehouse._create_or_update_sequences_and_picking_types())
        if picking_type_values:
            warehouse.write(picking_type_values)
    _translate_names(cr, _load_names())
