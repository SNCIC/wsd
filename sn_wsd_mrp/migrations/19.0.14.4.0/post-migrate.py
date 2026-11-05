"""Backfill the numerator / denominator of the existing BoM lines.

Lines created before this version only carry ``product_qty``. Without the
backfill they would show 1/1 next to a quantity such as 0.1, which contradicts
the rule "quantity = numerator / denominator".

The quantity stored so far came from a rounded export (6 decimals), so the
recovered pair is the closest fraction within ``MAX_FRACTION_DENOMINATOR``.
``product_qty`` is left untouched on purpose: only the fraction is added.
"""

from fractions import Fraction

MAX_FRACTION_DENOMINATOR = 20000
BATCH_SIZE = 5000


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT id, product_qty FROM mrp_bom_line ORDER BY id")
    updates = []
    for line_id, qty in cr.fetchall():
        fraction = Fraction(float(qty or 0.0)).limit_denominator(
            MAX_FRACTION_DENOMINATOR)
        updates.append((float(fraction.numerator), fraction.denominator, line_id))
        if len(updates) >= BATCH_SIZE:
            cr.executemany(
                "UPDATE mrp_bom_line SET qty_numerator = %s, "
                "qty_denominator = %s WHERE id = %s", updates)
            updates = []
    if updates:
        cr.executemany(
            "UPDATE mrp_bom_line SET qty_numerator = %s, "
            "qty_denominator = %s WHERE id = %s", updates)
