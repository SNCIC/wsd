# The company restriction rule used to be attached to base.group_user, which
# granted every internal user access to the inter-company agreements. The rule
# record itself is noupdate, so the group move has to be applied here.

RULE_XMLID = ('sn_wsd_inter_company', 'rule_sn_intercompany_agreement_company')
GROUP_XMLID = ('sales_team', 'group_sale_salesman')
INTERNAL_USER_XMLID = ('base', 'group_user')


def _res_id(cr, xmlid):
    module, name = xmlid
    cr.execute(
        "SELECT res_id FROM ir_model_data WHERE module = %s AND name = %s",
        (module, name),
    )
    row = cr.fetchone()
    return row[0] if row else None


def migrate(cr, version):
    if not version:
        return
    rule_id = _res_id(cr, RULE_XMLID)
    group_id = _res_id(cr, GROUP_XMLID)
    internal_user_id = _res_id(cr, INTERNAL_USER_XMLID)
    if not rule_id:
        return

    if internal_user_id:
        cr.execute(
            "DELETE FROM rule_group_rel WHERE rule_group_id = %s AND group_id = %s",
            (rule_id, internal_user_id),
        )
    if group_id:
        cr.execute(
            "INSERT INTO rule_group_rel (rule_group_id, group_id)"
            " SELECT %s, %s WHERE NOT EXISTS ("
            "  SELECT 1 FROM rule_group_rel WHERE rule_group_id = %s AND group_id = %s)",
            (rule_id, group_id, rule_id, group_id),
        )
