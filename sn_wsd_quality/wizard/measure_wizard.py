"""Measuring wizard of the incoming inspection items.

Opened from an inspection item line, it shows the lot header the legacy
inspection form carries (material, batch, supplier, quantities, limits) and
lets the inspector record every measurement of the item at once.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class QualityInspectionMeasureWizard(models.TransientModel):
    _name = 'sn.wsd.quality.inspection.measure.wizard'
    _description = 'Incoming Inspection Measuring Wizard'

    line_id = fields.Many2one(
        'sn.wsd.quality.inspection.line',
        string='Inspection Item',
        required=True,
        ondelete='cascade',
    )
    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection',
        string='Inspection',
        related='line_id.inspection_id',
        readonly=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Product',
        related='line_id.inspection_id.product_id', readonly=True,
    )
    product_categ_id = fields.Many2one(
        'product.category', string='Material Type',
        related='line_id.inspection_id.product_id.categ_id', readonly=True,
    )
    lot_id = fields.Many2one(
        'stock.lot', string='Internal Batch',
        related='line_id.inspection_id.lot_id', readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Supplier',
        related='line_id.inspection_id.picking_id.partner_id', readonly=True,
    )
    model_code = fields.Char(
        related='line_id.inspection_id.model_code', readonly=True,
    )
    lot_qty = fields.Integer(
        string='Received Qty', related='line_id.inspection_id.lot_qty',
        readonly=True,
    )
    inspect_qty = fields.Integer(
        string='Qty to Inspect', related='line_id.x_inspect_qty',
        readonly=True,
    )
    item_type = fields.Selection(
        related='line_id.item_type', readonly=True,
    )
    unit = fields.Char(related='line_id.unit', readonly=True)
    nominal_value = fields.Float(
        string='Standard Value', related='line_id.nominal_value',
        readonly=True,
    )
    upper_limit = fields.Float(
        string='Max Value', related='line_id.upper_limit', readonly=True,
    )
    lower_limit = fields.Float(
        string='Min Value', related='line_id.lower_limit', readonly=True,
    )
    x_report_file = fields.Binary(
        string='Inspection Report',
        related='line_id.inspection_id.x_report_file',
    )
    x_report_filename = fields.Char(
        string='Report Filename',
        related='line_id.inspection_id.x_report_filename',
    )
    value_ids = fields.One2many(
        'sn.wsd.quality.inspection.measure.wizard.line',
        'wizard_id',
        string='Inspection Results',
    )
    result_qty = fields.Integer(
        string='Qty', compute='_compute_result_qty',
    )

    @api.depends('value_ids')
    def _compute_result_qty(self):
        for wizard in self:
            wizard.result_qty = len(wizard.value_ids)

    @api.model
    def _get_context_line(self):
        line_id = (self.env.context.get('active_line_id')
                   or self.env.context.get('default_line_id'))
        if not line_id:
            return self.env['sn.wsd.quality.inspection.line']
        return self.env['sn.wsd.quality.inspection.line'].browse(
            line_id).exists()

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        line = self._get_context_line()
        if line:
            values.update({
                'line_id': line.id,
                'value_ids': [
                    fields.Command.create(row)
                    for row in line._measure_wizard_line_values()
                ],
            })
        return values

    def _reload_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inspection Measurement'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def _pending_rows(self):
        self.ensure_one()
        return self.value_ids.sorted(
            lambda row: (row.sequence, row.id)).filtered(
            lambda row: row.manual_result == 'pending'
            and not row.measured_value and not row.text_value)

    def action_generate_values(self):
        """Fill the rows still waiting for input with generated data."""
        self.ensure_one()
        line = self.line_id
        now = fields.Datetime.now()
        for index, row in enumerate(self._pending_rows(), 1):
            if line.item_type == 'numeric':
                row.write({
                    'measured_value': line._generate_random_value(index),
                    'measured_at': now,
                })
            else:
                row.write({'manual_result': 'pass', 'measured_at': now})
        return self._reload_action()

    def action_apply(self):
        self.ensure_one()
        line = self.line_id
        if line.inspection_id.state == 'done':
            raise UserError(_(
                'Reset the inspection before recording new measurements.'))
        sample_value_model = self.env[
            'sn.wsd.quality.inspection.sample.value']
        existing = line.sample_value_ids
        updated = set()
        for row in self.value_ids.sorted(
                lambda item: (item.sequence, item.id)):
            values = {
                'measured_value': row.measured_value,
                'text_value': row.text_value,
                'measured_at': row.measured_at or fields.Datetime.now(),
                'result': row.result,
                'defect_code_id': row.defect_code_id.id,
                'note': row.note,
            }
            candidates = existing.filtered(
                lambda value: value.id not in updated
                and value.sample_id.id == row.sample_id.id)
            if not candidates:
                candidates = existing.filtered(
                    lambda value: value.id not in updated)
            if candidates:
                record = candidates[0]
                updated.add(record.id)
                record.write(values)
            else:
                sample_value_model.create(dict(
                    values,
                    inspection_id=line.inspection_id.id,
                    line_id=line.id,
                    sample_id=row.sample_id.id,
                    sequence=row.sequence,
                ))
        # rows the inspector removed in the wizard go away with their values
        for value in existing:
            if value.id not in updated:
                value.unlink()
        return {'type': 'ir.actions.act_window_close'}


class QualityInspectionMeasureWizardLine(models.TransientModel):
    _name = 'sn.wsd.quality.inspection.measure.wizard.line'
    _description = 'Incoming Inspection Measuring Wizard Row'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'sn.wsd.quality.inspection.measure.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    sample_id = fields.Many2one(
        'sn.wsd.quality.inspection.sample', string='Sample',
    )
    measured_value = fields.Float(string='Measured Value')
    text_value = fields.Char(string='Text Value')
    measured_at = fields.Datetime(string='Measured At')
    manual_result = fields.Selection(
        [
            ('pending', 'Pending'),
            ('pass', 'Pass'),
            ('fail', 'Fail'),
            ('na', 'N/A'),
        ],
        string='Result',
        default='pending',
        help='Non-numeric items only. Legacy keypad entry: 0 qualifies, '
             '1 fails.',
    )
    result = fields.Selection(
        [
            ('pending', 'Pending'),
            ('pass', 'Pass'),
            ('fail', 'Fail'),
            ('na', 'N/A'),
        ],
        string='Conclusion',
        compute='_compute_result',
        store=True,
    )
    error_value = fields.Float(
        string='Deviation',
        compute='_compute_result',
        store=True,
    )
    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code', string='Defect Code',
    )
    note = fields.Char(string='Notes')
    item_type = fields.Selection(
        related='wizard_id.line_id.item_type', readonly=True,
    )
    unit = fields.Char(related='wizard_id.line_id.unit', readonly=True)
    lower_limit = fields.Float(
        related='wizard_id.line_id.lower_limit', readonly=True,
    )
    upper_limit = fields.Float(
        related='wizard_id.line_id.upper_limit', readonly=True,
    )

    @api.depends(
        'measured_value', 'text_value', 'manual_result',
        'wizard_id.line_id.item_type', 'wizard_id.line_id.nominal_value',
        'wizard_id.line_id.lower_limit', 'wizard_id.line_id.upper_limit',
        'wizard_id.line_id.expected_value', 'wizard_id.line_id.selection_values',
    )
    def _compute_result(self):
        for row in self:
            line = row.wizard_id.line_id
            if not line:
                row.error_value = 0.0
                row.result = 'pending'
                continue
            row.error_value = row.measured_value - line.nominal_value
            if row.manual_result == 'pending' \
                    and not row.measured_value and not row.text_value:
                row.result = 'pending'
                continue
            row.result = line._judge_item_value(
                line.item_type,
                measured=row.measured_value,
                text=row.text_value,
                expected=line.expected_value,
                allowed=line.selection_values,
                lower=line.lower_limit,
                upper=line.upper_limit,
                manual=row.manual_result,
            )
