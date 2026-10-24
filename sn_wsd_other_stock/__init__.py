import os

from babel.messages.pofile import read_po

from . import models

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

# Operation type of the warehouse and the term its name is translated from.
OPERATIONS = (
    ('OIN', 'Other Receipts'),
    ('OOUT', 'Other Deliveries'),
)


def post_init_hook(env):
    """Create the other operations of the warehouses that already exist.

    The operation types are created with the warehouse, so only the
    warehouses created before this module was installed are missing them.
    Their names are written in the user language once created, the module
    translations not being imported yet when the operations are made.
    """
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    warehouses._create_or_update_sequences_and_picking_types()
    _write_operation_names(env)


def _write_operation_names(env):
    """Write the translated names of the operations created at install."""
    path = os.path.join(MODULE_DIR, 'i18n', 'zh_CN.po')
    if not os.path.exists(path):
        return
    with open(path, 'rb') as handle:
        catalog = read_po(handle, locale='zh_CN')
    for code, msgid in OPERATIONS:
        message = catalog.get(msgid)
        if message is None or not message.string:
            continue
        env.cr.execute(
            """
            UPDATE stock_picking_type
               SET name = jsonb_set(
                       COALESCE(name, '{}'::jsonb), '{zh_CN}', to_jsonb(%s::text))
             WHERE sequence_code = %s
            """,
            (message.string, code),
        )
