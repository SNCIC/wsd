def migrate(cr, version):
    """Carry the former toll flag over to the new order type.

    The checkbox has been replaced by a document type: every order flagged as
    toll manufacturing becomes a toll manufacturing order, and the others keep
    the standard type they received by default.
    """
    if not version:
        return
    cr.execute(
        """
        UPDATE sale_order
           SET sn_order_type = 'toll'
         WHERE sn_is_toll IS TRUE
           AND (sn_order_type IS NULL OR sn_order_type = 'standard')
        """
    )
