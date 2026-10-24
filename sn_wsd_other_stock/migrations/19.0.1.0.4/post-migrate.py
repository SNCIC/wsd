import os

from babel.messages.pofile import read_po

from odoo import SUPERUSER_ID, api

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Operation type of the warehouse and the term its name is translated from.
OPERATIONS = (
    ('OIN', 'Other Receipts'),
    ('OOUT', 'Other Deliveries'),
)


def _load_names():
    """Names of the two operations, read from the translations of the module.

    The operations are created while the module is installed, before Odoo
    imports its translations, so their names were stored in English. The
    translated names are read from the po file instead of writing Chinese in
    the source.
    """
    path = os.path.join(MODULE_DIR, 'i18n', 'zh_CN.po')
    if not os.path.exists(path):
        return {}
    with open(path, 'rb') as handle:
        catalog = read_po(handle, locale='zh_CN')
    names = {}
    for _code, msgid in OPERATIONS:
        message = catalog.get(msgid)
        if message is not None and message.string:
            names[msgid] = message.string
    return names


def migrate(cr, version):
    names = _load_names()
    if not names:
        return
    # The names are written as translations of the value already stored, so
    # the translated column keeps its source value and gains the Chinese one.
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
