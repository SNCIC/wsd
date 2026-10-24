from babel.messages.pofile import read_po

from odoo import SUPERUSER_ID, api
from odoo.tools.misc import file_path


def _load_names():
    """Names of the two operations, read from the translations of the module.

    The operations are created while the module is installed, before Odoo
    imports its translations, so their names were stored in English. The
    translated names are read from the po file instead of writing Chinese in
    the source.
    """
    try:
        path = file_path('sn_wsd_other_stock/i18n/zh_CN.po')
    except FileNotFoundError:
        return {}
    with open(path, 'rb') as handle:
        catalog = read_po(handle, locale='zh_CN')
    return {
        msgid: catalog.get(msgid).string
        for msgid in ('Other Receipts', 'Other Deliveries')
        if catalog.get(msgid) is not None
    }


def migrate(cr, version):
    names = _load_names()
    if not names:
        return
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'zh_CN'})
    warehouses = env['stock.warehouse'].with_context(active_test=False).search([])
    for warehouse in warehouses:
        if warehouse.other_in_type_id and names.get('Other Receipts'):
            warehouse.other_in_type_id.write({'name': names['Other Receipts']})
        if warehouse.other_out_type_id and names.get('Other Deliveries'):
            warehouse.other_out_type_id.write({'name': names['Other Deliveries']})
