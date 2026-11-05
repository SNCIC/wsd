from odoo import models


class SnSmtOperationMixin(models.AbstractModel):
    _inherit = 'sn.smt.operation.mixin'

    def _check_material_common_rules(self, mes_order, online_material, material_lot):
        result = super()._check_material_common_rules(
            mes_order,
            online_material,
            material_lot,
        )
        material_lot._msd_validate_for_use(auto_unseal=True)
        return result
