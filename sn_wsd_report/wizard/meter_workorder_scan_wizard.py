from odoo import _, fields, models
from odoo.exceptions import UserError


class MeterWorkorderScanWizard(models.TransientModel):
    _name = 'sn.wsd.workorder.scan.wizard'
    _description = 'Workorder Meter Scan Wizard'

    workcenter_id = fields.Many2one('mrp.workcenter')
    workorder_id = fields.Many2one('mrp.workorder')
    mode = fields.Selection(
        [('start', 'Start'), ('complete', 'Complete')],
        default='complete',
        required=True,
    )
    serial_no = fields.Char(required=True)
    operator_code = fields.Char()
    note = fields.Char()
    seal_no = fields.Char()
    carton_no = fields.Char()
    pallet_no = fields.Char()
    aging_batch_id = fields.Many2one('sn.wsd.meter.aging.batch')
    aging_slot_no = fields.Char()
    override_route = fields.Boolean(string='Override Route Check')

    def _resolve_workorder(self):
        self.ensure_one()
        if self.workorder_id:
            return self.workorder_id
        if self.workcenter_id:
            workorder = self.workcenter_id.x_active_workorder_ids[:1]
            if workorder:
                self.workorder_id = workorder
                return workorder
        raise UserError(_('No active work order is available for this work center.'))

    def action_apply(self):
        self.ensure_one()
        workorder = self._resolve_workorder()
        terminal_wizard = self.env['sn.wsd.workorder.terminal.wizard'].create({
            'workcenter_id': self.workcenter_id.id,
            'workorder_id': workorder.id,
            'mode': 'manual',
            'report_type': self.mode,
            'serial_no': self.serial_no,
            'operator_code': self.operator_code,
            'remark': self.note,
            'seal_no': self.seal_no,
            'carton_no': self.carton_no,
            'pallet_no': self.pallet_no,
            'aging_batch_id': self.aging_batch_id.id,
            'aging_slot_no': self.aging_slot_no,
            'override_route': self.override_route,
            'qty_in': 1.0,
            'qty_ok': 1.0 if self.mode == 'complete' else 0.0,
        })
        return terminal_wizard.action_submit()
