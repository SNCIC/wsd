from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """产品级替代关系（product_substitute_rel）一次性迁移为全局
    替代料规则（substitute-rule R4）。幂等，可安全重跑。"""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['sn.wsd.substitute.rule']._migrate_product_substitute_rules()
