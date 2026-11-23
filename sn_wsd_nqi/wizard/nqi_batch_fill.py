"""Batch fill wizard: set one column on many selected mirror rows.

Bound to the high-frequency tables via server actions (see
views/nqi_batch_fill_actions.xml). The touched column goes through the
normal write path, so the missing bookkeeping refreshes automatically.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class NqiBatchFill(models.TransientModel):
    _name = 'sn.wsd.nqi.batch.fill'
    _description = 'NQI Batch Fill'

    target_model = fields.Char(string='Target Model', required=True)
    field_name = fields.Char(
        string='Column', required=True,
        help='Mirror field name (lower snake), e.g. error_limit.')
    value = fields.Char(string='Value')

    def action_apply(self):
        self.ensure_one()
        model = self.env[self.target_model].sudo()
        if self.field_name not in model._fields:
            raise UserError(_(
                'Column %s does not exist on %s.',
                self.field_name, self.target_model))
        records = model.browse(self.env.context.get('active_ids', []))
        records.write({self.field_name: self.value or ''})
        return {'type': 'ir.actions.act_window_close'}
