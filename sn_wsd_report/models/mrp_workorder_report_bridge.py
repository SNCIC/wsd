from odoo import _, api, fields, models


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    workorder_report_ids = fields.One2many(
        'mrp.workorder.report',
        'workorder_id',
        string='Workorder Reports',
        readonly=True,
    )
    workorder_report_count = fields.Integer(string='Report Count', compute='_compute_workorder_report_summary')
    workorder_report_qty_in_total = fields.Float(string='Report Input Qty', compute='_compute_workorder_report_summary')
    workorder_report_qty_ok_total = fields.Float(string='Report OK Qty', compute='_compute_workorder_report_summary')
    workorder_report_qty_ng_total = fields.Float(string='Report NG Qty', compute='_compute_workorder_report_summary')
    workorder_report_qty_scrap_total = fields.Float(string='Report Scrap Qty', compute='_compute_workorder_report_summary')
    workorder_report_qty_repair_total = fields.Float(string='Report Repair Qty', compute='_compute_workorder_report_summary')
    workorder_report_qty_rework_total = fields.Float(string='Report Rework Qty', compute='_compute_workorder_report_summary')

    def write(self, vals):
        if 'qty_produced' in vals:
            return super().write(vals)
        sync_fields = {
            'x_meter_qty_input',
            'x_meter_qty_pass',
            'x_meter_qty_fail',
            'x_meter_qty_scrap',
            'x_meter_qty_rework',
        }
        should_sync = (
            not self.env.context.get('skip_report_sync')
            and not self.env.context.get('bypass_duration_calculation')
            and vals.get('state') not in {'done', 'cancel'}
            and bool(sync_fields.intersection(vals))
        )
        result = super().write(vals)
        if should_sync:
            self._sync_report_totals()
        return result

    def action_sync_meter_qty(self):
        for workorder in self:
            workorder._sync_report_totals()
        return True

    def _reset_in_progress_serial_context(self):
        for workorder in self:
            if workorder.state in ('done', 'cancel'):
                continue
            if workorder.production_id.product_tracking != 'serial':
                continue
            workorder._meter_sync_packed_production_quantities()

    def action_open_terminal_report_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_terminal_client_action',
            'name': _('Terminal Report'),
            'context': {
                'default_workorder_id': self.id,
                'default_workcenter_id': self.x_mes_workcenter_id.id,
                'default_operator_code': self.x_meter_operator_code,
                'default_device_id': self.x_meter_equipment_id.id,
                'default_qty_in': self._suggest_report_input_qty(),
                'default_report_type': 'complete' if self.state == 'progress' else 'start',
            },
        }

    def action_open_workorder_reports(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Workorder Reports'),
            'res_model': 'mrp.workorder.report',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('workorder_id', '=', self.id)],
            'context': {
                'default_workorder_id': self.id,
                'default_production_id': self.production_id.id,
            },
        }

    @api.depends(
        'workorder_report_ids.state',
        'workorder_report_ids.qty_in',
        'workorder_report_ids.qty_ok',
        'workorder_report_ids.qty_ng',
        'workorder_report_ids.qty_scrap',
        'workorder_report_ids.qty_repair',
        'workorder_report_ids.qty_rework',
        'workorder_report_ids.qty_out',
    )
    def _compute_workorder_report_summary(self):
        for workorder in self:
            reports = workorder.workorder_report_ids.filtered(lambda report: report.state != 'cancelled')
            workorder.workorder_report_count = len(reports)
            workorder.workorder_report_qty_in_total = sum(reports.mapped('qty_in'))
            workorder.workorder_report_qty_ok_total = sum(reports.mapped('qty_ok'))
            workorder.workorder_report_qty_ng_total = sum(reports.mapped('qty_ng'))
            workorder.workorder_report_qty_scrap_total = sum(reports.mapped('qty_scrap'))
            workorder.workorder_report_qty_repair_total = sum(reports.mapped('qty_repair'))
            workorder.workorder_report_qty_rework_total = sum(reports.mapped('qty_rework'))

    def _get_previous_output_qty(self):
        self.ensure_one()
        previous_workorders = self.production_id.workorder_ids.filtered(
            lambda wo: wo.id != self.id and (wo.sequence, wo.id) < (self.sequence, self.id)
        )
        return sum(previous_workorders.mapped('qty_produced'))

    def _get_available_report_qty(self):
        self.ensure_one()
        if not self.production_id:
            return 0.0
        previous_output_qty = self._get_previous_output_qty()
        reported_here = self.qty_produced or 0.0
        carried_qty = self.qty_reported_from_previous_wo or 0.0
        available_qty = previous_output_qty - carried_qty - reported_here
        return max(available_qty, 0.0)

    def _suggest_report_input_qty(self):
        self.ensure_one()
        return self._get_available_report_qty()

    def _sync_report_totals(self):
        for workorder in self:
            reports = workorder.workorder_report_ids.filtered(lambda report: report.state != 'cancelled')
            total_in = sum(reports.mapped('qty_in'))
            total_ok = sum(reports.mapped('qty_ok'))
            total_ng = sum(reports.mapped('qty_ng'))
            total_scrap = sum(reports.mapped('qty_scrap'))
            total_repair = sum(reports.mapped('qty_repair'))
            total_rework = sum(reports.mapped('qty_rework'))
            total_out = sum(reports.mapped('qty_out'))
            vals = {
                'x_meter_qty_input': total_in,
                'x_meter_qty_pass': total_ok,
                'x_meter_qty_fail': total_ng,
                'x_meter_qty_scrap': total_scrap,
                'x_meter_qty_rework': total_rework,
            }
            if workorder.state not in ('done', 'cancel'):
                vals['qty_produced'] = total_out
            workorder.with_context(skip_report_sync=True).write(vals)
            if workorder.production_id:
                workorder.production_id._update_meter_flow_state()

    def action_register_terminal_report(
        self,
        source_type='manual',
        report_type='complete',
        operator_code=None,
        device=False,
        external_event_id=False,
        event_time=False,
        qty_in=0.0,
        qty_ok=0.0,
        qty_ng=0.0,
        qty_scrap=0.0,
        qty_repair=0.0,
        qty_rework=0.0,
        loss_reason=False,
        serial_no=False,
        remark=False,
        payload_json=False,
    ):
        self.ensure_one()
        report_model = self.env['mrp.workorder.report']
        existing = report_model.search([
            ('company_id', '=', self.company_id.id),
            ('external_event_id', '=', external_event_id),
        ], limit=1) if external_event_id else report_model
        if existing:
            return existing
        report_vals = {
            'production_id': self.production_id.id,
            'manufacturing_batch_id': self.x_manufacturing_batch_id.id,
            'workorder_id': self.id,
            'source_type': source_type,
            'report_type': report_type,
            'operator_code': operator_code,
            'device_id': device.id if device else False,
            'external_event_id': external_event_id,
            'event_time': event_time or fields.Datetime.now(),
            'qty_in': qty_in,
            'qty_ok': qty_ok,
            'qty_ng': qty_ng,
            'qty_scrap': qty_scrap,
            'qty_repair': qty_repair,
            'qty_rework': qty_rework,
            'loss_reason_id': loss_reason.id if loss_reason else False,
            'remark': remark,
            'payload_json': payload_json,
        }
        report = report_model.create(report_vals)
        if serial_no:
            line_result = 'ok'
            if qty_scrap:
                line_result = 'scrap'
            elif qty_repair or qty_rework:
                line_result = 'repair'
            elif qty_ng:
                line_result = 'ng'
            report.write({
                'line_ids': [fields.Command.create({
                    'serial_no': serial_no,
                    'result': line_result,
                    'operator_id': self.env.user.id,
                    'device_id': device.id if device else False,
                    'ng_reason_id': loss_reason.id if line_result == 'ng' and loss_reason else False,
                })],
            })
        return report

    def get_terminal_dashboard_data(self):
        self.ensure_one()
        reports = self.workorder_report_ids.filtered(lambda report: report.state != 'cancelled')
        recent_reports = reports.sorted(lambda report: (report.event_time or fields.Datetime.now(), report.id), reverse=True)[:8]
        return {
            'workorder_id': self.id,
            'workorder_name': self.display_name,
            'production_id': self.production_id.id,
            'production_name': self.production_id.display_name,
            'workcenter_id': self.x_mes_workcenter_id.id,
            'workcenter_name': self.x_mes_workcenter_id.display_name,
            'workcenter_code': self.x_meter_workcenter_code,
            'station_name': self.x_mes_workcenter_id.display_name,
            'operation_type': self.x_meter_operation_type,
            'device_id': self.x_meter_equipment_id.id,
            'device_name': self.x_meter_equipment_id.display_name,
            'state': self.state,
            'operator_code': self.x_meter_operator_code,
            'qty_input': self.x_meter_qty_input,
            'qty_pass': self.x_meter_qty_pass,
            'qty_fail': self.x_meter_qty_fail,
            'qty_scrap': self.x_meter_qty_scrap,
            'qty_rework': self.x_meter_qty_rework,
            'qty_output_total': self.qty_produced,
            'qty_output_total_label': _('Cumulative Output Qty'),
            'available_qty': self._get_available_report_qty(),
            'previous_output_qty': self._get_previous_output_qty(),
            'report_count': len(reports),
            'recent_reports': [
                {
                    'id': report.id,
                    'name': report.name,
                    'event_time': report.event_time,
                    'report_type': report.report_type,
                    'source_type': report.source_type,
                    'qty_in': report.qty_in,
                    'qty_ok': report.qty_ok,
                    'qty_ng': report.qty_ng,
                    'qty_scrap': report.qty_scrap,
                    'qty_repair': report.qty_repair,
                    'qty_rework': report.qty_rework,
                    'qty_out': report.qty_out,
                    'serials': report.line_ids.mapped('serial_no'),
                }
                for report in recent_reports
            ],
        }

    def action_submit_terminal_payload(self, payload):
        self.ensure_one()
        payload = payload or {}
        wizard = self.env['sn.wsd.workorder.terminal.wizard'].create({
            'workcenter_id': payload.get('workcenter_id') or self.x_mes_workcenter_id.id,
            'workorder_id': self.id,
            'mode': payload.get('mode') or 'manual',
            'report_type': payload.get('report_type') or 'complete',
            'operator_code': payload.get('operator_code') or self.x_meter_operator_code,
            'device_id': payload.get('device_id') or self.x_meter_equipment_id.id,
            'external_event_id': payload.get('external_event_id'),
            'event_time': payload.get('event_time') or fields.Datetime.now(),
            'qty_in': payload.get('qty_in', 0.0),
            'qty_ok': payload.get('qty_ok', 0.0),
            'qty_ng': payload.get('qty_ng', 0.0),
            'qty_scrap': payload.get('qty_scrap', 0.0),
            'qty_repair': payload.get('qty_repair', 0.0),
            'qty_rework': payload.get('qty_rework', 0.0),
            'loss_reason_id': payload.get('loss_reason_id'),
            'serial_no': payload.get('serial_no'),
            'remark': payload.get('remark'),
            'payload_json': payload.get('payload_json'),
            'seal_no': payload.get('seal_no'),
            'carton_no': payload.get('carton_no'),
            'pallet_no': payload.get('pallet_no'),
            'aging_batch_id': payload.get('aging_batch_id'),
            'aging_slot_no': payload.get('aging_slot_no'),
            'override_route': payload.get('override_route', False),
        })
        wizard.action_submit()
        return self.get_terminal_dashboard_data()

    def action_open_meter_scan_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Terminal Report',
            'res_model': 'sn.wsd.workorder.terminal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_workorder_id': self.id,
                'default_workcenter_id': self.x_mes_workcenter_id.id,
                'default_mode': 'manual',
                'default_report_type': 'complete' if self.state == 'progress' else 'start',
                'default_operator_code': self.x_meter_operator_code,
                'default_device_id': self.x_meter_equipment_id.id,
                'default_qty_in': self._suggest_report_input_qty(),
            },
        }

    def action_meter_scan_start(self, serial_number, operator_code=None, note=None, override_route=False, source_type='manual'):
        self.ensure_one()
        result = self.action_mes_start(
            serial_number=serial_number,
            operator_code=operator_code,
            note=note,
            override_route=override_route,
        )
        if result.get('error'):
            return result
        archive = self._meter_get_or_create_serial_archive(serial_number)
        archive.current_workorder_id = self
        archive.production_id = self.production_id
        if self.x_meter_operation_type == 'aging_load':
            self._meter_apply_aging_transition(archive, operator_code=operator_code, note=note)
        else:
            archive.action_apply_business_state(
                'assembled' if archive.state == 'created' else archive.state,
                workorder=self,
                operator_code=operator_code,
            )
        self.action_register_terminal_report(
            source_type=source_type,
            report_type='start',
            operator_code=operator_code,
            device=self.x_meter_equipment_id,
            event_time=fields.Datetime.now(),
            qty_in=1.0,
            qty_ok=0.0,
            qty_ng=0.0,
            qty_scrap=0.0,
            qty_repair=0.0,
            qty_rework=0.0,
            serial_no=serial_number,
            remark=note,
        )
        self.action_sync_meter_qty()
        return {**result, 'internal_serial_id': archive.id, 'meter_state': archive.state}

    def action_meter_scan_complete(
        self,
        serial_number,
        operator_code=None,
        note=None,
        seal_no=None,
        carton_no=None,
        pallet_no=None,
        aging_batch_id=None,
        aging_slot_no=None,
        override_route=False,
        source_type='manual',
    ):
        self.ensure_one()
        result = self.action_mes_complete(
            serial_number=serial_number,
            operator_code=operator_code,
            note=note,
            override_route=override_route,
        )
        if result.get('error'):
            return result
        archive = self._meter_get_or_create_serial_archive(serial_number)
        target_state = self._meter_target_state_for_operation(result='pass')
        batch = self.env['sn.wsd.meter.aging.batch'].browse(aging_batch_id).exists() if aging_batch_id else self.env['sn.wsd.meter.aging.batch']
        sync_packed_quantities = self.x_meter_operation_type == 'packing'
        if self.x_meter_operation_type == 'aging_load':
            self._meter_apply_aging_transition(archive, operator_code=operator_code, note=note, batch=batch, slot_no=aging_slot_no)
        elif self.x_meter_operation_type == 'aging_unload':
            self._meter_apply_aging_transition(archive, operator_code=operator_code, note=note, batch=batch, unload=True)
        elif sync_packed_quantities:
            archive.action_apply_business_state(target_state, workorder=self, operator_code=operator_code)
            self._meter_apply_pack_transition(
                archive,
                operator_code=operator_code,
                note=note,
                seal_no=seal_no,
                carton_no=carton_no,
                pallet_no=pallet_no,
            )
        else:
            archive.action_apply_business_state(target_state, workorder=self, operator_code=operator_code)
        self.action_register_terminal_report(
            source_type=source_type,
            report_type='complete',
            operator_code=operator_code,
            device=self.x_meter_equipment_id,
            event_time=fields.Datetime.now(),
            qty_in=1.0,
            qty_ok=1.0,
            qty_ng=0.0,
            qty_scrap=0.0,
            qty_repair=0.0,
            qty_rework=0.0,
            serial_no=serial_number,
            remark=note,
        )
        self.action_sync_meter_qty()
        self.action_mes_finish_if_complete()
        self._reset_in_progress_serial_context()
        if sync_packed_quantities:
            self._meter_sync_packed_production_quantities()
        return {**result, 'internal_serial_id': archive.id, 'meter_state': archive.state}
