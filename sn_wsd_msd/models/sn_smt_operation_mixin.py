from odoo import models


class SnSmtOperationMixin(models.AbstractModel):
    _inherit = 'sn.smt.operation.mixin'

    def _check_material_common_rules(self, production, online_material, material_lot, require_issue=False, require_positive_qty=False):
        result = super()._check_material_common_rules(
            production,
            online_material,
            material_lot,
            require_issue=require_issue,
            require_positive_qty=require_positive_qty,
        )
        material_lot._msd_validate_for_use(auto_unseal=True)
        return result
