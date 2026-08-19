# -*- coding: utf-8 -*-
"""为日志功能上线前已在线的制令单回填上线日志（上线人取单据创建人近似，
时间取既有上线时间）。"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    from odoo import SUPERUSER_ID
    from odoo.api import Environment
    env = Environment(cr, SUPERUSER_ID, {})
    Order = env['sn.wsd.mes.order']
    Log = env['sn.wsd.mes.order.log']
    backfilled = 0
    for order in Order.search([('x_online_date', '!=', False)]):
        if Log.search_count([('mes_order_id', '=', order.id),
                             ('action', '=', 'online')]):
            continue
        Log.create({
            'mes_order_id': order.id,
            'action': 'online',
            'user_id': order.create_uid.id,
            'date': order.x_online_date,
        })
        backfilled += 1
    _logger.info("sn_wsd_mrp 19.0.7.0.6: backfilled %d online log line(s)",
                 backfilled)
