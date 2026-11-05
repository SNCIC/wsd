from odoo.api import Environment, SUPERUSER_ID


def migrate(cr, version):
    """Recompute the translated stored complete_name after names became
    translatable in 19.0.4.1.0, once per active language."""
    env = Environment(cr, SUPERUSER_ID, {})
    categories = env['sn.wsd.exception.category'].with_context(active_test=False).search([])
    for lang in env['res.lang'].search([]).mapped('code'):
        categories.with_context(lang=lang)._compute_complete_name()
