from odoo import SUPERUSER_ID, Command, api


def migrate(cr, version):
    """Restore the standard inventory rights.

    The previous versions opened the inventory application to every internal
    user and carried a dedicated group for the validation. Both are undone:
    the other receipts and other deliveries go back to the stock users, the
    only ones Odoo lets into the inventory application.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})

    group = env.ref(
        'sn_wsd_stock.group_sn_wsd_warehouse_user',
        raise_if_not_found=False)
    if group:
        env['ir.model.data'].search([
            ('module', '=', 'sn_wsd_stock'),
            ('name', '=', 'group_sn_wsd_warehouse_user'),
        ]).unlink()
        group.unlink()

    base_group = env.ref('base.group_user')
    stock_user = env.ref('stock.group_stock_user', raise_if_not_found=False)
    if stock_user and stock_user in base_group.implied_ids:
        base_group.write({'implied_ids': [Command.unlink(stock_user.id)]})
