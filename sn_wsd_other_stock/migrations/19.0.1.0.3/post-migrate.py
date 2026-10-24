import logging
import os

from babel.messages.pofile import read_po

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    for msgid in ('Other Receipts', 'Other Deliveries'):
        message = catalog.get(msgid)
        if message is not None and message.string:
            names[msgid] = message.string
    return names


def migrate(cr, version):
    names = _load_names()
    _logger.info('sn_wsd_other_stock: operation names to write: %s', names)
    if not names:
        return
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'zh_CN'})
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    for warehouse in warehouses:
        if warehouse.other_in_type_id and names.get('Other Receipts'):
            warehouse.other_in_type_id.with_context(lang='zh_CN').write({
                'name': names['Other Receipts'],
            })
        if warehouse.other_out_type_id and names.get('Other Deliveries'):
            warehouse.other_out_type_id.with_context(lang='zh_CN').write({
                'name': names['Other Deliveries'],
            })
