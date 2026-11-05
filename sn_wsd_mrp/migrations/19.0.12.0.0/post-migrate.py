def migrate(cr, version):
    """Backfill binding.product_id from the drawing key (one product per
    drawing number; pick the first match)."""
    cr.execute("""
        UPDATE sn_wsd_process_route_drawing d
        SET product_id = sub.id
        FROM (
            SELECT DISTINCT ON (pt.default_code) pp.id, pt.default_code
            FROM product_product pp
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE pt.default_code IS NOT NULL AND pt.default_code != ''
            ORDER BY pt.default_code, pp.id
        ) sub
        WHERE d.product_id IS NULL
          AND d.x_drawing_no = sub.default_code
    """)
