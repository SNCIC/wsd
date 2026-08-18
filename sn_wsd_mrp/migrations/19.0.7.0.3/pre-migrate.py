# -*- coding: utf-8 -*-
"""图号统一：产品图号唯一载体 = 内部参考 default_code（界面显示"图号"），
自定义字段 x_drawing_no 退役（产品模板/变体 + 工艺路线）。

跑在 pre 阶段：此时模型代码尚未重载，老列必然还在，用纯 SQL 完成
（ORM 读不到已删除的字段）。

1. 回填：default_code 为空而 x_drawing_no 有值的变体，图号拷入
   default_code；再镜像到模板存储 compute 列（与
   _compute_template_field_from_variant_field 同口径：取最小 id 变体）。
   两者都有且不同的保留 default_code（只记日志）。
2. 重锚定：图号绑定表 sn_wsd_process_route_drawing 的关联键从老
   x_drawing_no 改为产品的 default_code，避免换键后绑定失效。老图号
   对应多个不同 default_code（歧义）或会撞唯一约束的跳过并记日志。
3. 删除三张表上的退役列（Odoo 升级不会自动删列）。
"""

import logging

from odoo.tools import sql

_logger = logging.getLogger(__name__)

_RETIRED_COLUMNS = [
    ('product_template', 'x_drawing_no'),
    ('product_product', 'x_drawing_no'),
    ('sn_wsd_process_route', 'x_drawing_no'),
]


def migrate(cr, version):
    if not version:
        return
    if not sql.column_exists(cr, 'product_template', 'x_drawing_no'):
        # fresh install on the new key already -- nothing to migrate
        return

    # 1) backfill variants, then mirror to the template compute column
    cr.execute("""
        UPDATE product_product
        SET default_code = x_drawing_no
        WHERE x_drawing_no IS NOT NULL AND x_drawing_no <> ''
          AND (default_code IS NULL OR default_code = '')
    """)
    backfilled = cr.rowcount
    cr.execute("""
        UPDATE product_template pt
        SET default_code = src.default_code
        FROM (SELECT DISTINCT ON (product_tmpl_id)
                      product_tmpl_id, default_code
              FROM product_product
              WHERE default_code IS NOT NULL AND default_code <> ''
              ORDER BY product_tmpl_id, id) src
        WHERE pt.id = src.product_tmpl_id
          AND (pt.default_code IS NULL OR pt.default_code = '')
    """)
    cr.execute("""
        SELECT count(*) FROM product_template
        WHERE x_drawing_no IS NOT NULL AND x_drawing_no <> ''
          AND default_code IS NOT NULL AND default_code <> ''
          AND default_code <> x_drawing_no
    """)
    kept = cr.fetchone()[0]

    # 2) re-anchor bindings: old drawing key -> product default_code
    cr.execute("""
        SELECT DISTINCT x_drawing_no, default_code FROM product_product
        WHERE x_drawing_no IS NOT NULL AND x_drawing_no <> ''
          AND default_code IS NOT NULL AND default_code <> ''
          AND default_code <> x_drawing_no
    """)
    mapping = {}
    ambiguous = set()
    for old, new in cr.fetchall():
        if old in mapping and mapping[old] != new:
            ambiguous.add(old)
        else:
            mapping[old] = new
    for old in ambiguous:
        mapping.pop(old, None)

    moved, skipped = 0, 0
    for old, new in mapping.items():
        cr.execute(
            "SELECT id FROM sn_wsd_process_route_drawing WHERE x_drawing_no = %s",
            (old,))
        drawing_ids = [row[0] for row in cr.fetchall()]
        for drawing_id in drawing_ids:
            # skip the move when the target key already exists on another
            # binding of the same route or the same (company, workshop,
            # side) group -- both unique constraints
            cr.execute("""
                SELECT 1
                  FROM sn_wsd_process_route_drawing d2
                  JOIN sn_wsd_process_route_drawing d1 ON d1.id = %s
                 WHERE d2.id != d1.id
                   AND d2.x_drawing_no = %s
                   AND (d2.route_id = d1.route_id
                        OR (d2.company_id = d1.company_id
                            AND d2.x_workshop_id IS NOT DISTINCT FROM d1.x_workshop_id
                            AND d2.x_side IS NOT DISTINCT FROM d1.x_side))
                 LIMIT 1
            """, (drawing_id, new))
            if cr.fetchone():
                skipped += 1
                continue
            cr.execute(
                "UPDATE sn_wsd_process_route_drawing SET x_drawing_no = %s WHERE id = %s",
                (new, drawing_id))
            moved += 1

    # 3) drop the retired columns
    for table, column in _RETIRED_COLUMNS:
        if sql.column_exists(cr, table, column):
            cr.execute('ALTER TABLE "%s" DROP COLUMN "%s"' % (table, column))

    _logger.info(
        "sn_wsd_mrp 19.0.7.0.3: drawing number unified into default_code "
        "(variants backfilled: %d, conflicting default_code kept: %d, "
        "bindings re-anchored: %d, skipped on collision: %d, ambiguous "
        "old keys: %d)", backfilled, kept, moved, skipped, len(ambiguous))
