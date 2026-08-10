from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WorkorderTerminalWizard(models.TransientModel):
    _name = 'sn.wsd.workorder.terminal.wizard'
    _description = 'Workorder Terminal Wizard'

    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center')
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order')
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='workorder_id.production_id',
        readonly=True,
    )
    mode = fields.Selection(
        [('manual', 'Manual'), ('pda', 'PDA'), ('machine', 'Machine'), ('api', 'API')],
        string='Source Type',
        required=True,
        default='manual',
    )
    report_type = fields.Selection(
        [('start', 'Start'), ('complete', 'Complete')],
        string='Report Type',
        required=True,
        default='complete',
    )
    operator_code = fields.Char(string='Operator Code')
    device_id = fields.Many2one('maintenance.equipment', string='Device')
    external_event_id = fields.Char(string='External Event ID')
    event_time = fields.Datetime(string='Event Time', default=fields.Datetime.now, required=True)
    qty_in = fields.Float(string='Input Qty', digits='Product Unit', default=0.0)
    qty_ok = fields.Float(string='OK Qty', digits='Product Unit', default=0.0)
    qty_ng = fields.Float(string='NG Qty', digits='Product Unit', default=0.0)
    qty_scrap = fields.Float(string='Scrap Qty', digits='Product Unit', default=0.0)
    qty_repair = fields.Float(string='Repair Qty', digits='Product Unit', default=0.0)
    qty_rework = fields.Float(string='Rework Qty', digits='Product Unit', default=0.0)
    loss_reason_id = fields.Many2one('sn.wsd.quality.defect.code', string='Loss Reason')
    serial_no = fields.Char(string='SN')
    remark = fields.Text(string='Remark')
    payload_json = fields.Text(string='Payload JSON')
    seal_no = fields.Char(string='Seal No')
    carton_no = fields.Char(string='Carton No')
    pallet_no = fields.Char(string='Pallet No')
    aging_batch_id = fields.Many2one('sn.wsd.meter.aging.batch', string='Aging Batch')
    aging_slot_no = fields.Char(string='Aging Slot No')
    override_route = fields.Boolean(string='Override Route Check')
    available_qty = fields.Float(
        string='Available Qty',
        compute='_compute_available_qty',
        readonly=True,
    )
    previous_output_qty = fields.Float(
        string='Previous Output Qty',
        compute='_compute_available_qty',
        readonly=True,
    )
    operation_type = fields.Selection(
        related='workorder_id.x_meter_operation_type',
        string='Operation Type',
        readonly=True,
    )
    station_code = fields.Char(
        related='workorder_id.x_meter_workcenter_code',
        string='Work Center Code',
        readonly=True,
    )
    report_output_qty = fields.Float(
        string='Reported Output Qty',
        compute='_compute_report_preview',
        readonly=True,
    )
    report_balance_qty = fields.Float(
        string='Balance Qty',
        compute='_compute_report_preview',
        readonly=True,
    )
    is_serial_flow = fields.Boolean(
        string='Serial Flow',
        compute='_compute_report_preview',
        readonly=True,
    )

    @api.depends('workorder_id')
    def _compute_available_qty(self):
        for wizard in self:
            available_qty = 0.0
            previous_output_qty = 0.0
            workorder = wizard.workorder_id
            if workorder:
                available_qty = workorder._get_available_report_qty()
                previous_output_qty = workorder._get_previous_output_qty()
            wizard.available_qty = available_qty
            wizard.previous_output_qty = previous_output_qty

    @api.depends(
        'serial_no',
        'mode',
        'qty_in',
        'qty_ok',
        'qty_ng',
        'qty_scrap',
        'qty_repair',
        'available_qty',
    )
    def _compute_report_preview(self):
        for wizard in self:
            is_serial_flow = bool(wizard.serial_no and wizard.mode in ('manual', 'pda'))
            output_qty = wizard.qty_ok + wizard.qty_ng + wizard.qty_scrap + wizard.qty_repair
            wizard.is_serial_flow = is_serial_flow
            wizard.report_output_qty = 1.0 if is_serial_flow and wizard.report_type == 'complete' else output_qty
            wizard.report_balance_qty = max(wizard.available_qty - wizard.qty_in, 0.0)

    @api.onchange('workcenter_id')
    def _onchange_workcenter_id(self):
        for wizard in self:
            if wizard.workcenter_id and not wizard.workorder_id:
                wizard.workorder_id = wizard.workcenter_id.x_active_workorder_ids[:1]

    @api.onchange('workorder_id')
    def _onchange_workorder_id(self):
        for wizard in self:
            if wizard.workorder_id:
                wizard.workcenter_id = wizard.workorder_id.x_mes_workcenter_id
                wizard.operator_code = wizard.operator_code or wizard.workorder_id.x_meter_operator_code
                wizard.device_id = wizard.device_id or wizard.workorder_id.x_meter_equipment_id
                if wizard.qty_in <= 0:
                    wizard.qty_in = wizard.workorder_id._suggest_report_input_qty()

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

    def action_submit(self):
        self.ensure_one()
        workorder = self._resolve_workorder()
        if self.serial_no and self.mode in ('manual', 'pda'):
            if self.report_type == 'start':
                result = workorder.action_meter_scan_start(
                    self.serial_no,
                    operator_code=self.operator_code,
                    note=self.remark,
                    override_route=self.override_route,
                    source_type=self.mode,
                )
            else:
                result = workorder.action_meter_scan_complete(
                    self.serial_no,
                    operator_code=self.operator_code,
                    note=self.remark,
                    seal_no=self.seal_no,
                    carton_no=self.carton_no,
                    pallet_no=self.pallet_no,
                    aging_batch_id=self.aging_batch_id.id,
                    aging_slot_no=self.aging_slot_no,
                    override_route=self.override_route,
                    source_type=self.mode,
                )
            if isinstance(result, dict) and result.get('error'):
                raise UserError(_("%s\n\nError Code: %s") % (result.get('message') or result['error'], result['error']))
            latest_report = workorder.workorder_report_ids.filtered(
                lambda report: report.source_type == 'manual' and report.report_type == self.report_type
            )[:1]
            if latest_report:
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Workorder Report'),
                    'res_model': 'mrp.workorder.report',
                    'view_mode': 'form',
                    'res_id': latest_report.id,
                    'target': 'current',
                }
            return result
        report = workorder.action_register_terminal_report(
            source_type=self.mode,
            report_type=self.report_type,
            operator_code=self.operator_code,
            device=self.device_id,
            external_event_id=self.external_event_id,
            event_time=self.event_time,
            qty_in=self.qty_in,
            qty_ok=self.qty_ok,
            qty_ng=self.qty_ng,
            qty_scrap=self.qty_scrap,
            qty_repair=self.qty_repair,
            qty_rework=self.qty_rework,
            loss_reason=self.loss_reason_id,
            serial_no=self.serial_no,
            remark=self.remark,
            payload_json=self.payload_json,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Workorder Report'),
            'res_model': 'mrp.workorder.report',
            'view_mode': 'form',
            'res_id': report.id,
            'target': 'current',
        }
