from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OqcRetestWizard(models.TransientModel):
    """In-place retest confirmation on an OQC inspection
    (oqc-disposition-closure tasks 4.2/4.3, design decision 3).

    Collects the current-board values of every required item plus the
    retest reason. Real values are re-judged by the shared item rules --
    an out-of-limit number can never be forced to pass. Only the current
    board is touched; a passing retest syncs the station fact through the
    shared pass kernel when the latest pass was NG."""

    _name = 'sn.wsd.quality.oqc.retest.wizard'
    _description = 'OQC Board Retest Confirmation'

    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection', required=True, ondelete='cascade')
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='Board', required=True,
        domain="[('id', 'in', serial_candidate_ids)]")
    serial_candidate_ids = fields.Many2many(
        'sn.wsd.serial.identity',
        'sn_wsd_quality_oqc_retest_wizard_serial_rel',
        'wizard_id', 'serial_id', string='Candidate Boards')
    reason = fields.Text(required=True)
    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code', string='Defect Code',
        help='Defect identity of the board, recorded on the event chain '
             'before the closure is allowed.')
    line_ids = fields.One2many(
        'sn.wsd.quality.oqc.retest.wizard.line', 'wizard_id',
        string='Retest Values')

    @api.onchange('inspection_id', 'serial_identity_id')
    def _onchange_load_board(self):
        self.line_ids = False
        self.serial_candidate_ids = False
        inspection = self.inspection_id
        if not inspection:
            return
        self.serial_candidate_ids = inspection._oqc_known_serials()
        board = self.serial_identity_id
        if not board:
            return
        cells = inspection.cell_ids.filtered(
            lambda c: c.serial_identity_id == board)
        lines = []
        for line in inspection.line_ids.sorted('sequence'):
            cell = cells.filtered(lambda c, lid=line: c.line_id == lid)[:1]
            lines.append((0, 0, {
                'line_id': line.id,
                'measured_value': cell.measured_value if cell else False,
                'text_value': cell.text_value if cell else False,
                'manual_result': (cell.manual_result if cell
                                  and cell.manual_result != 'pending'
                                  else False) or 'pending',
            }))
        self.line_ids = lines

    def action_apply(self):
        self.ensure_one()
        if not (self.reason or '').strip():
            raise ValidationError(_('Describe the retest reason.'))
        cell_values = {}
        for row in self.line_ids:
            line = row.line_id
            vals = {}
            if line.item_type == 'numeric':
                vals['measured_value'] = row.measured_value
                vals['manual_result'] = 'pending'
            elif line.item_type in ('text', 'selection'):
                vals['text_value'] = row.text_value
                vals['manual_result'] = 'pending'
            else:  # pass_fail / boolean style: the operator's verdict
                vals['manual_result'] = row.manual_result
            cell_values[line.id] = vals
        # every required item needs a usable value this round
        for row in self.line_ids:
            if not row.line_id.required:
                continue
            if row.line_id.item_type == 'numeric' \
                    and row.measured_value is False:
                raise ValidationError(_(
                    'Enter the retest value of item %s.',
                    row.line_id.name))
            if row.line_id.item_type in ('text', 'selection') \
                    and not (row.text_value or '').strip():
                raise ValidationError(_(
                    'Enter the retest value of item %s.',
                    row.line_id.name))
            if row.line_id.item_type not in ('numeric', 'text', 'selection') \
                    and row.manual_result in (False, 'pending'):
                raise ValidationError(_(
                    'Give the retest verdict of item %s.',
                    row.line_id.name))
        self.inspection_id._oqc_action_retest(
            self.serial_identity_id, self.reason, cell_values,
            defect_code_id=self.defect_code_id.id)
        return {'type': 'ir.actions.act_window_close'}


class OqcRetestWizardLine(models.TransientModel):
    _name = 'sn.wsd.quality.oqc.retest.wizard.line'
    _description = 'OQC Board Retest Value'

    wizard_id = fields.Many2one(
        'sn.wsd.quality.oqc.retest.wizard', required=True,
        ondelete='cascade')
    line_id = fields.Many2one(
        'sn.wsd.quality.inspection.line', required=True,
        ondelete='cascade')
    item_code = fields.Char(related='line_id.item_code', readonly=True)
    item_type = fields.Selection(
        related='line_id.item_type', readonly=True)
    lower_limit = fields.Float(related='line_id.lower_limit', readonly=True)
    upper_limit = fields.Float(related='line_id.upper_limit', readonly=True)
    measured_value = fields.Float(string='Measured Value')
    text_value = fields.Char(string='Text Value')
    manual_result = fields.Selection(
        [('pending', 'Pending'), ('pass', 'Pass'), ('fail', 'Fail'),
         ('na', 'N/A')],
        string='Verdict', default='pending', required=True)
