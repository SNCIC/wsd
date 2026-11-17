# Custom module access must be granted through the business groups instead of
# base.group_user. Earlier versions made every internal user imply the shop
# floor group; drop that link so the internal user role no longer inherits it.

MODULE = 'sn_wsd_workorder'


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        DELETE FROM res_groups_implied_rel
        WHERE gid = (SELECT res_id FROM ir_model_data
                     WHERE module = 'base' AND name = 'group_user')
          AND hid = (SELECT res_id FROM ir_model_data
                     WHERE module = %s AND name = 'group_sn_wsd_shop_floor_user')
        """,
        (MODULE,),
    )
