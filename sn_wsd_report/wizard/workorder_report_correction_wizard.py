from odoo import _, fields, models
from odoo.exceptions import UserError


class WorkorderReportCorrectionWizard(models.TransientModel):
    _name = 'mrp.workorder.report.correction.wizard'
    _description = 'Workorder Report Correction Wizard'

    report_id = fields.Many2one(
        'mrp.workorder.report',
        string='Workorder Report',
        required=True,
        readonly=True,
    )
    reason = fields.Text(string='Correction Reason', required=True)
    qty_ok = fields.Float(string='Correct OK Quantity', digits='Product Unit')
    qty_ng = fields.Float(string='Correct NG Quantity', digits='Product Unit')
    qty_scrap = fields.Float(string='Correct Scrap Quantity', digits='Product Unit')
    qty_repair = fields.Float(string='Correct Repair Quantity', digits='Product Unit')
    qty_rework = fields.Float(string='Correct Rework Quantity', digits='Product Unit')

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('mrp.group_mrp_manager'):
            raise UserError(_('Only Manufacturing Managers can correct reports.'))
        report = self.report_id
        if report.state != 'posted':
            raise UserError(_('Only posted reports can be corrected.'))
        if report.workorder_id.state in ('done', 'cancel'):
            raise UserError(_('A completed or cancelled work order cannot be corrected from this screen.'))
        if report.line_ids:
            raise UserError(_('Serial-number reports must be corrected through the serial or quality flow.'))
        if report.source_type in ('machine', 'api'):
            raise UserError(_('Machine and API reports require an external correction event.'))
        values = {
            'qty_ok': self.qty_ok,
            'qty_ng': self.qty_ng,
            'qty_scrap': self.qty_scrap,
            'qty_repair': self.qty_repair,
            'qty_rework': self.qty_rework,
        }
        if any(value < 0 for value in values.values()):
            raise UserError(_('Corrected quantities cannot be negative.'))
        if sum(values.values()) > report.qty_in:
            raise UserError(_('Corrected output cannot exceed the original input quantity.'))
        replacement = report.copy_data({
            **values,
            'name': _('New'),
            'state': 'posted',
            'correction_of_id': report.id,
            'correction_reason': self.reason,
            'correction_user_id': self.env.user.id,
            'correction_time': fields.Datetime.now(),
            'external_event_id': False,
        })
        report.action_cancel()
        replacement_report = self.env['mrp.workorder.report'].create(replacement[0])
        report.write({
            'correction_reason': self.reason,
            'correction_user_id': self.env.user.id,
            'correction_time': fields.Datetime.now(),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Corrected Workorder Report'),
            'res_model': 'mrp.workorder.report',
            'view_mode': 'form',
            'res_id': replacement_report.id,
            'target': 'current',
        }
