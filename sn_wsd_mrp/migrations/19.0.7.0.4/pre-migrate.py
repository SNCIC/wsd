# -*- coding: utf-8 -*-
"""生产面默认单面（x_production_side default='single'）。

存量回填：未声明生产面、且全部绑定图号都对应单面板产品的路线补
'single'（单面板路线必然产单面）。以下情况不猜，留待人工声明：
- 绑定产品是双面板、或图号解析不到产品；
- 该路线任一图号在同公司同车间已被别的 single 路线占用（补了会撞
  “一图号一车间每面一条路线”的唯一约束，说明本来就是重复绑定）。

绑定行的存储 related x_side 随路线同步。"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        UPDATE sn_wsd_process_route r
           SET x_production_side = 'single'
         WHERE r.x_production_side IS NULL
           AND EXISTS (SELECT 1 FROM sn_wsd_process_route_drawing d
                        WHERE d.route_id = r.id)
           AND NOT EXISTS (
                SELECT 1 FROM sn_wsd_process_route_drawing d
                LEFT JOIN product_product p ON p.default_code = d.x_drawing_no
                 WHERE d.route_id = r.id
                   AND (p.id IS NULL OR p.x_board_side IS DISTINCT FROM 'single'))
           AND NOT EXISTS (
                SELECT 1
                  FROM sn_wsd_process_route_drawing d1
                  JOIN sn_wsd_process_route_drawing d2
                    ON d2.x_drawing_no = d1.x_drawing_no
                   AND d2.company_id = d1.company_id
                   AND d2.x_workshop_id IS NOT DISTINCT FROM d1.x_workshop_id
                   AND d2.route_id != d1.route_id
                  JOIN sn_wsd_process_route r2 ON r2.id = d2.route_id
                 WHERE d1.route_id = r.id
                   AND r2.x_production_side = 'single')
    """)
    routes = cr.rowcount
    cr.execute("""
        UPDATE sn_wsd_process_route_drawing d
           SET x_side = 'single'
          FROM sn_wsd_process_route r
         WHERE d.route_id = r.id
           AND r.x_production_side = 'single'
           AND d.x_side IS DISTINCT FROM 'single'
    """)
    bindings = cr.rowcount
    _logger.info(
        "sn_wsd_mrp 19.0.7.0.4: production side defaulted to single "
        "(routes backfilled: %d, bindings synced: %d)", routes, bindings)
