from babel.messages.pofile import read_po

from odoo import SUPERUSER_ID, api
from odoo.tools.misc import file_path

# Operation type of the warehouse and the term its name is translated from.
OPERATIONS = (
    ('OIN', 'Other Receipts'),
    ('OOUT', 'Other Deliveries'),
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


def migrate(cr, version):
    names = _load_names()
    if not names:
        return
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
