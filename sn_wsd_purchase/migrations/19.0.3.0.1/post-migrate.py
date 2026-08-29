def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        UPDATE purchase_request_line
           SET approved_qty = product_qty
         WHERE approved_qty = 0
           AND product_qty > 0
        """
    )
