from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Drop the dedicated groups of the first release.

    Access rights now follow the manufacturing convention of the project
    (mrp.group_mrp_user / mrp.group_mrp_manager), so the empty toll groups
    would only add noise in the group list.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in (
        'sn_wsd_toll.group_sn_toll_user',
        'sn_wsd_toll.group_sn_toll_manager',
    ):
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            group.unlink()
