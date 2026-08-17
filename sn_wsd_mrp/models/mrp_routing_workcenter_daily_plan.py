from odoo import models


class MrpRoutingWorkcenterDailyPlan(models.Model):
    """Suppress standard work-order generation entirely.

    In Odoo 19 work orders are produced by the stored computed field
    ``mrp.production.workorder_ids`` (``_compute_workorder_ids``). For each BOM
    operation it calls ``operation._skip_operation_line(product, ...)``; this is
    the officially intended extension point (its docstring says "can be inherited
    to add custom control"). Returning ``True`` here means the work order is
    never created, instead of the previous generate-then-delete approach.

    Going forward there is no work-order concept: station-passing is driven by
    the process route / daily-order operations (and serial tracking), not by
    ``mrp.workorder``. So every operation line is skipped for every product.

    Note: the previous override of ``_action_compute_consumption`` was dead code
    -- that method does not exist in Odoo 19, so ``super()`` would raise and the
    override was never invoked.
    """
    _inherit = 'mrp.routing.workcenter'

    def _skip_operation_line(self, product, never_attribute_values=False):
        # No work-order concept: never generate standard work orders. Station
        # passing is handled by the route / daily-order operations instead.
        return True
