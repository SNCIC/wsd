from odoo import api, models, _
from odoo.exceptions import UserError


class MrpBomLineSubstitute(models.Model):
    _inherit = 'mrp.bom.line.substitute'

    @staticmethod
    def _raise_legacy_substitute_error():
        raise UserError(_(
            'BoM-line substitute design is deprecated. Maintain allowed substitutes on the product through engineering BoMs instead.'
        ))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('allow_legacy_bom_substitute_write'):
            self._raise_legacy_substitute_error()
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('allow_legacy_bom_substitute_write'):
            self._raise_legacy_substitute_error()
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('allow_legacy_bom_substitute_write'):
            self._raise_legacy_substitute_error()
        return super().unlink()
