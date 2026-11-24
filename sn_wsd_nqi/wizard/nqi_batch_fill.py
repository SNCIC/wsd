"""Batch fill wizard: set one column on many selected mirror rows.

Reached from the "Batch Fill Missing Columns" entry of every mirror
table (views/nqi_binding_actions.xml). The column is picked by its
label; writes go through the normal write path, so the missing
bookkeeping refreshes by itself.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

# envelope and bookkeeping columns are platform-side: not fillable here
NOT_FILLABLE = (
    'company_id', 'push_state', 'missing_fields', 'missing_count',
    'enterprise_code', 'nqi_write_date', 'handle_flag', 'handle_date',
    'notice_no', 'data_source',
)


class NqiBatchFill(models.TransientModel):
    _name = 'sn.wsd.nqi.batch.fill'
    _description = 'NQI Batch Fill'

    target_model = fields.Char(string='Target Model', required=True)
    field_id = fields.Many2one(
        'ir.model.fields', string='Column', required=True,
        domain=[('model', '=', target_model),
                ('ttype', 'in', ('char', 'text')),
                ('name', 'not in', list(NOT_FILLABLE))])
    value = fields.Char(string='Value')
    only_empty = fields.Boolean(
        string='Only Empty Cells', default=True,
        help='Fill the rows where the column is still empty; clear it to '
             'overwrite every selected row.')

    def action_apply(self):
        self.ensure_one()
        model = self.env[self.target_model].sudo()
        rows = model.browse(self.env.context.get('active_ids', []))
        rows = rows.filtered(lambda row: row.push_state != 'pushed')
        if self.only_empty:
            rows = rows.filtered(lambda row: not row[self.field_id.name])
        if not rows:
            raise UserError(_(
                'No row to fill: pushed rows are read-only and the other '
                'selected rows already carry a value.'))
        rows.write({self.field_id.name: self.value or ''})
        return {'type': 'ir.actions.act_window_close'}
