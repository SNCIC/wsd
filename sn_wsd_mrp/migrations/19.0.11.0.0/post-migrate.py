# -*- coding: utf-8 -*-
"""面别口径收敛：BOM 行取消 'all'（All Sides），只留 single/top/bottom。

存量 'all' 行按 BOM 产品板型归位：双面板 → 'top'（默认面），其余
（单面板/未声明板型）→ 'single'。未声明板型的产品本来就排不了制令
单，归 'single' 不影响业务。
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE mrp_bom_line bl
        SET x_board_side = CASE
                WHEN pt.x_board_side = 'double' THEN 'top'
                ELSE 'single'
            END
        FROM mrp_bom b
        JOIN product_template pt ON pt.id = b.product_tmpl_id
        WHERE b.id = bl.bom_id
          AND bl.x_board_side = 'all'
    """)
    _logger.info("board side collapse: %s 'all' BOM lines migrated", cr.rowcount)
