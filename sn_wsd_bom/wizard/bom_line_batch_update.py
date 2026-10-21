from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SnBomLineBatchUpdate(models.TransientModel):
    """Batch update of the values shared by several BOM component lines.

    Only the fields that make sense to align across BOMs are offered: the
    component usage (numerator / denominator), the board side, the advance
    issue flag and the sequence. The component itself and its unit of measure
    are left out on purpose, they are per line decisions.
    """

    _name = 'sn.bom.line.batch.update'
    _description = 'BOM Line Batch Update'

    line_ids = fields.Many2many(
        'mrp.bom.line',
        'sn_bom_line_batch_update_rel',
        'wizard_id',
        'line_id',
        string='BOM Lines',
        required=True,
    )
    line_count = fields.Integer(
        string='Selected Lines',
        compute='_compute_line_count',
    )

    update_usage = fields.Boolean(string='Update Usage')
    qty_numerator = fields.Float(
        string='Numerator',
        default=1.0,
        digits=(16, 6),
    )
    qty_denominator = fields.Integer(
        string='Denominator',
        default=1,
    )

    update_board_side = fields.Boolean(string='Update Board Side')
    x_board_side = fields.Selection(
        selection='_selection_board_side',
        string='Board Side',
    )

    update_advance_issue = fields.Boolean(string='Update Advance Issue')
    x_advance_issue = fields.Boolean(string='Advance Issue')

    update_sequence = fields.Boolean(string='Update Sequence')
    sequence = fields.Integer(string='Sequence', default=1)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)

    def _selection_board_side(self):
        field = self.env['mrp.bom.line']._fields.get('x_board_side')
        return field.selection if field else []

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'mrp.bom.line':
            line_ids = self.env.context.get('active_ids') or []
            values['line_ids'] = [fields.Command.set(line_ids)]
        return values

    def action_apply(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Select at least one BOM line to update.'))
        values = {}
        if self.update_usage:
            if not self.qty_denominator:
                raise UserError(
                    _('The denominator of the component quantity must not be zero.'))
            values.update({
                'qty_numerator': self.qty_numerator,
                'qty_denominator': self.qty_denominator,
            })
        if self.update_board_side:
            if not self.x_board_side:
                raise UserError(_('Choose the board side to set.'))
            values['x_board_side'] = self.x_board_side
        if self.update_advance_issue:
            values['x_advance_issue'] = self.x_advance_issue
        if self.update_sequence:
            values['sequence'] = self.sequence
        if not values:
            raise UserError(_('Choose at least one value to update.'))
        self.line_ids.write(values)
        return {'type': 'ir.actions.act_window_close'}
