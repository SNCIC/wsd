from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Remove the single receipt detail report.

    The report listed purchase request lines and was replaced by the receipt,
    quality control and storage detail reports of sn_wsd_stock, which list the
    moves of each reception operation. Its records are left in the database by
    the upgrade because they no longer appear in the data files.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in (
            'sn_wsd_purchase.menu_sn_purchase_receipt_detail',
            'sn_wsd_purchase.action_sn_purchase_receipt_detail',
            'sn_wsd_purchase.view_sn_purchase_receipt_detail_list',
    ):
        record = env.ref(xmlid, raise_if_not_found=False)
        if record:
            record.unlink()
