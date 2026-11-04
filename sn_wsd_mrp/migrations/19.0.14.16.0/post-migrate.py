from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Replace the intermediate store rules by the final derivation.

    The first iteration (19.0.14.14.0/15.0) supplied the store from stock with
    an extra transfer, which duplicated the requisition flow. Those rules carry
    no origin flag, so they are removed here by location before the derivation
    runs again; the derivation itself only keeps the rules a store really needs
    (a store still hanging under the warehouse stock needs none) and flags what
    it creates.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    StockRule = env['stock.rule']
    mto_route = env.ref('stock.route_warehouse0_mto', raise_if_not_found=False)
    manufacture_route = env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
    workshops = env['sn.mrp.workshop'].search([('component_location_id', '!=', False)])
    locations = workshops.component_location_id
    route_ids = [route.id for route in (mto_route | manufacture_route) if route]
    if locations and route_ids:
        stale = StockRule.search([
            ('route_id', 'in', route_ids),
            ('x_workshop_store_rule', '=', False),
            '|',
            '&', ('location_src_id', 'in', locations.ids),
                 ('location_dest_id.usage', '=', 'production'),
            ('location_dest_id', 'in', locations.ids),
        ])
        # A rule still referenced by a move cannot be removed: retire it so the
        # rule search ignores it.
        used = env['stock.move'].search([('rule_id', 'in', stale.ids)]).rule_id
        (stale - used).unlink()
        used.write({'active': False})
    workshops._ensure_line_side_replenishment()
