import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def sanitize_json(value):
    if isinstance(value, dict):
        return {str(key): sanitize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


class MrpWorkorderReport(models.Model):
    _name = 'mrp.workorder.report'
    _description = 'Manufacturing Workorder Report'
    _order = 'event_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Report Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
        index=True,
        check_company=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        index=True,
        check_company=True,
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        required=True,
        index=True,
        check_company=True,
    )
    operation_id = fields.Many2one(
        'mrp.routing.workcenter',
        string='Operation',
        related='workorder_id.operation_id',
        store=True,
        readonly=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        related='workorder_id.workcenter_id',
        store=True,
        readonly=True,
    )
    source_type = fields.Selection(
        [('manual', 'Manual'), ('pda', 'PDA'), ('machine', 'Machine'), ('api', 'API')],
        string='Source Type',
        required=True,
        default='manual',
        index=True,
    )
    report_type = fields.Selection(
        [('start', 'Start'), ('complete', 'Complete')],
        string='Report Type',
        required=True,
        default='complete',
        index=True,
    )
    operator_id = fields.Many2one(
        'res.users',
        string='Operator',
        default=lambda self: self.env.user,
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        check_company=True,
    )
    operator_code = fields.Char(string='Operator Code', index=True)
    device_id = fields.Many2one(
        'maintenance.equipment',
        string='Device',
        check_company=True,
        index=True,
    )
    external_event_id = fields.Char(string='External Event ID', index=True, copy=False)
    report_batch_no = fields.Char(string='Report Batch No.', index=True)
    event_time = fields.Datetime(
        string='Event Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    qty_in = fields.Float(string='Input Qty', digits='Product Unit', default=0.0)
    qty_ok = fields.Float(string='OK Qty', digits='Product Unit', default=0.0)
    qty_ng = fields.Float(string='NG Qty', digits='Product Unit', default=0.0)
    qty_scrap = fields.Float(string='Scrap Qty', digits='Product Unit', default=0.0)
    qty_repair = fields.Float(string='Repair Qty', digits='Product Unit', default=0.0)
    qty_rework = fields.Float(string='Rework Qty', digits='Product Unit', default=0.0)
    qty_out = fields.Float(
        string='Output Qty',
        digits='Product Unit',
        compute='_compute_qty_out',
        store=True,
    )
    loss_reason_id = fields.Many2one(
        'sn.wsd.quality.defect.code',
        string='Loss Reason',
        check_company=True,
    )
    remark = fields.Text(string='Remark')
    payload_json = fields.Text(string='Payload JSON', copy=False)
    payload = fields.Json(string='Payload', copy=False)
    state = fields.Selection(
        [('draft', 'Draft'), ('posted', 'Posted'), ('cancelled', 'Cancelled')],
        string='Status',
        required=True,
        default='posted',
        index=True,
    )
    correction_of_id = fields.Many2one(
        'mrp.workorder.report', string='Corrected Report', readonly=True, copy=False,
        check_company=True, index=True,
    )
    correction_ids = fields.One2many(
        'mrp.workorder.report', 'correction_of_id', string='Correction Reports',
        readonly=True,
    )
    correction_reason = fields.Text(string='Correction Reason', readonly=True, copy=False)
    correction_user_id = fields.Many2one('res.users', string='Corrected By', readonly=True, copy=False)
    correction_time = fields.Datetime(string='Corrected On', readonly=True, copy=False)
    line_ids = fields.One2many(
        'mrp.workorder.report.line',
        'report_id',
        string='SN Lines',
    )
    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result',
        string='Test Result',
        check_company=True,
        copy=False,
    )
    travel_id = fields.Many2one(
        'sn.wsd.mes.sn.travel',
        string='Travel Event',
        check_company=True,
        copy=False,
    )

    _report_event_company_unique = models.Constraint(
        'unique(company_id, external_event_id)',
        'The external event ID must be unique per company.',
    )

    @api.depends('qty_ok', 'qty_ng', 'qty_scrap', 'qty_repair')
    def _compute_qty_out(self):
        for record in self:
            record.qty_out = record.qty_ok + record.qty_ng + record.qty_scrap + record.qty_repair

    @api.constrains('production_id', 'workorder_id')
    def _check_workorder_scope(self):
        for record in self:
            if record.workorder_id.production_id != record.production_id:
                raise ValidationError(_('The selected work order must belong to the selected manufacturing order.'))
            if record.mes_order_id and record.production_id not in record.mes_order_id.production_id:
                raise ValidationError(_('The selected MES order must belong to the selected manufacturing order.'))

    @api.constrains('qty_in', 'qty_ok', 'qty_ng', 'qty_scrap', 'qty_repair', 'qty_rework')
    def _check_quantities(self):
        for record in self:
            quantities = [
                record.qty_in,
                record.qty_ok,
                record.qty_ng,
                record.qty_scrap,
                record.qty_repair,
                record.qty_rework,
            ]
            if any(quantity < 0 for quantity in quantities):
                raise ValidationError(_('Reported quantities cannot be negative.'))
            if record.qty_out > record.qty_in:
                raise ValidationError(_('The output quantity cannot be greater than the input quantity.'))

    @api.constrains('line_ids', 'workorder_id')
    def _check_sn_line_duplicates(self):
        for record in self.filtered('line_ids'):
            serial_numbers = record.line_ids.mapped('serial_no')
            if len(serial_numbers) != len(set(serial_numbers)):
                raise ValidationError(_('The same SN cannot appear twice in one report.'))

    @api.constrains('external_event_id', 'source_type')
    def _check_external_event_id(self):
        for record in self:
            if record.source_type in ('machine', 'api') and not record.external_event_id:
                raise ValidationError(_('Machine and API reports must provide an external event ID.'))

    @api.constrains('line_ids')
    def _check_line_company(self):
        for record in self:
            if record.line_ids.filtered(lambda line: line.company_id != record.company_id):
                raise ValidationError(_('All report lines must belong to the same company as the report.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mrp.workorder.report') or _('New')
            if not vals.get('mes_order_id'):
                workorder = self.env['mrp.workorder'].browse(vals.get('workorder_id')).exists() if vals.get('workorder_id') else self.env['mrp.workorder']
                production = self.env['mrp.production'].browse(vals.get('production_id')).exists() if vals.get('production_id') else workorder.production_id
                mes_order = workorder.x_mes_order_id or production.x_mes_order_id
                if mes_order:
                    vals['mes_order_id'] = mes_order.id
            payload = vals.get('payload')
            payload_json = vals.get('payload_json')
            if payload_json and not payload:
                vals['payload'] = sanitize_json(json.loads(payload_json))
            elif payload:
                vals['payload'] = sanitize_json(payload)
                vals['payload_json'] = json.dumps(vals['payload'], ensure_ascii=True)
        records = super().create(vals_list)
        records._sync_workorders()
        return records

    def write(self, vals):
        payload = vals.get('payload')
        payload_json = vals.get('payload_json')
        if payload_json and not payload:
            vals = dict(vals)
            vals['payload'] = sanitize_json(json.loads(payload_json))
        elif payload:
            vals = dict(vals)
            vals['payload'] = sanitize_json(payload)
            vals['payload_json'] = json.dumps(vals['payload'], ensure_ascii=True)
        result = super().write(vals)
        self._sync_workorders()
        return result

    def unlink(self):
        workorders = self.mapped('workorder_id')
        result = super().unlink()
        workorders._sync_report_totals()
        return result

    def action_cancel(self):
        if any(report.state == 'cancelled' for report in self):
            return True
        self.write({'state': 'cancelled'})
        return True

    def action_open_correction_wizard(self):
        self.ensure_one()
        if not self.env.user.has_group('mrp.group_mrp_manager'):
            raise UserError(_('Only Manufacturing Managers can correct reports.'))
        if self.state != 'posted':
            raise UserError(_('Only posted reports can be corrected.'))
        if self.workorder_id.state in ('done', 'cancel'):
            raise UserError(_('A completed or cancelled work order cannot be corrected from this screen.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Correct Workorder Report'),
            'res_model': 'mrp.workorder.report.correction.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_report_id': self.id},
        }

    def action_post(self):
        self.write({'state': 'posted'})
        return True

    def _sync_workorders(self):
        self.mapped('workorder_id')._sync_report_totals()



class MrpWorkorderReportLine(models.Model):
    _name = 'mrp.workorder.report.line'
    _description = 'Manufacturing Workorder Report Line'
    _order = 'test_time desc, id desc'
    _check_company_auto = True

    report_id = fields.Many2one(
        'mrp.workorder.report',
        string='Workorder Report',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='report_id.company_id',
        store=True,
        readonly=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='report_id.production_id',
        store=True,
        readonly=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='report_id.mes_order_id',
        store=True,
        readonly=True,
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        related='report_id.workorder_id',
        store=True,
        readonly=True,
    )
    serial_no = fields.Char(string='SN', required=True, index=True)
    serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Meter Serial',
        check_company=True,
        index=True,
    )
    result = fields.Selection(
        [('ok', 'OK'), ('ng', 'NG'), ('repair', 'Repair'), ('scrap', 'Scrap')],
        string='Result',
        required=True,
        default='ok',
        index=True,
    )
    ng_reason_id = fields.Many2one(
        'sn.wsd.quality.defect.code',
        string='NG Reason',
        check_company=True,
    )
    device_id = fields.Many2one(
        'maintenance.equipment',
        string='Device',
        check_company=True,
    )
    test_time = fields.Datetime(
        string='Test Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    test_value_json = fields.Text(string='Test Value JSON', copy=False)
    test_value = fields.Json(string='Test Value', copy=False)
    firmware_version = fields.Char(string='Firmware Version')
    operator_id = fields.Many2one('res.users', string='Operator')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            test_value = vals.get('test_value')
            test_value_json = vals.get('test_value_json')
            if test_value_json and not test_value:
                vals['test_value'] = sanitize_json(json.loads(test_value_json))
            elif test_value:
                vals['test_value'] = sanitize_json(test_value)
                vals['test_value_json'] = json.dumps(vals['test_value'], ensure_ascii=True)
            if vals.get('serial_no') and not vals.get('serial_id'):
                report_company_id = vals.get('company_id')
                if not report_company_id and vals.get('report_id'):
                    report_company_id = self.env['mrp.workorder.report'].browse(vals['report_id']).company_id.id
                serial = self.env['sn.wsd.internal.serial'].search([
                    ('serial_no', '=', vals['serial_no']),
                    ('company_id', '=', report_company_id or self.env.company.id),
                ], limit=1)
                if serial:
                    vals['serial_id'] = serial.id
        return super().create(vals_list)

