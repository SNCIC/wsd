from odoo import models


class MrpRoutingWorkcenterDailyPlan(models.Model):
    """Suppress standard work-order generation entirely.

    Odoo's routing hook is kept only to prevent standard execution rows from
    being generated. Station passing is driven by MES order route operations.

    Note: the previous override of ``_action_compute_consumption`` was dead code
    -- that method does not exist in Odoo 19, so ``super()`` would raise and the
    override was never invoked.
    """
    _inherit = 'mrp.routing.workcenter'

    def _skip_operation_line(self, product, never_attribute_values=False):
        # No work-order concept: never generate standard work orders. Station
        # passing is handled by the route / daily-order operations instead.
        return True
