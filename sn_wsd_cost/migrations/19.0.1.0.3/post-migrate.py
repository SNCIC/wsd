"""Rebuild the stored purchase prices rounded to the cents of the currency.

``_sn_purchase_line_unit_cost`` converted the price with the default rounding
of ``res.currency._convert``, which rounds to the cents of the currency even
when the purchase is already in the company currency. A material bought at
0.00565 per unit was therefore stored as 0.01, and the BoMs showed that price.

The conversion no longer rounds, so every price written so far has to be
rebuilt. The stored cost of the BoM lines follows through their compute
dependencies.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['purchase.order.line'].search([
        ('order_id.state', 'in', ('purchase', 'done')),
        ('display_type', '=', False),
        ('product_qty', '>', 0),
    ])
    templates = lines.product_id.product_tmpl_id
    templates._sn_refresh_latest_purchase_price(env.company)
    # The components follow their product through the compute dependencies, but
    # the recomputation is lazy: the stored value only changes when the line is
    # read. Recompute them here so the tables are consistent straight away.
    bom_lines = env['mrp.bom.line'].search([('product_id', 'in', lines.product_id.ids)])
    bom_lines._compute_sn_cost()
    _logger.info(
        'Latest purchase prices rebuilt on %s product(s), %s BoM line(s).',
        len(templates), len(bom_lines))
