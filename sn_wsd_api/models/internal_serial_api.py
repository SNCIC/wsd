from odoo import api, fields, models


class InternalSerial(models.Model):
    _inherit = 'sn.wsd.internal.serial'

    x_nameplate_code = fields.Char(string='Nameplate Code', index=True, copy=False)
    x_mes_repair_state = fields.Selection(
        [
            ('none', 'None'),
            ('repair_required', 'Repair Required'),
            ('repairing', 'Repairing'),
            ('rework', 'Rework'),
        ],
        string='MES Repair State',
        default='none',
        index=True,
        copy=False,
    )
    x_rework_source_workorder_id = fields.Many2one('mrp.workorder', string='Rework Source Work Order', check_company=True, copy=False)
    x_rework_entry_workorder_id = fields.Many2one('mrp.workorder', string='Rework Entry Work Order', check_company=True, copy=False)
    x_rework_exit_workorder_id = fields.Many2one('mrp.workorder', string='Rework Exit Work Order', check_company=True, copy=False)
    mes_travel_ids = fields.One2many(
        'sn.wsd.mes.sn.travel',
        'internal_serial_id',
        string='MES Travel History',
        readonly=True,
    )
    mes_test_result_ids = fields.One2many(
        'sn.wsd.mes.test.result',
        'internal_serial_id',
        string='MES Test Results',
        readonly=True,
    )
    test_result_count = fields.Integer(compute='_compute_api_counts')
    travel_count = fields.Integer(compute='_compute_api_counts')

    def _compute_api_counts(self):
        travel_model = self.env['sn.wsd.mes.sn.travel']
        test_model = self.env['sn.wsd.mes.test.result']
        for record in self:
            record.travel_count = travel_model.search_count([('internal_serial_id', '=', record.id)])
            record.test_result_count = test_model.search_count([('internal_serial_id', '=', record.id)])

    def _workorder_in_current_rework_window(self, workorder):
        self.ensure_one()
        if self.x_mes_repair_state != 'rework' or not workorder:
            return False
        entry = self.x_rework_entry_workorder_id
        exit_workorder = self.x_rework_exit_workorder_id or self.x_rework_source_workorder_id
        if not entry or not exit_workorder:
            return False
        if workorder.production_id != entry.production_id or workorder.production_id != exit_workorder.production_id:
            return False
        workorders = workorder.production_id.workorder_ids
        entry_key = (entry.sequence, entry.id)
        exit_key = (exit_workorder.sequence, exit_workorder.id)
        current_key = (workorder.sequence, workorder.id)
        return entry_key <= current_key <= exit_key

    def _mark_rework_started(self, entry_workorder, source_workorder=False):
        for record in self:
            record.write({
                'x_mes_repair_state': 'rework',
                'x_rework_entry_workorder_id': entry_workorder.id if entry_workorder else False,
                'x_rework_source_workorder_id': source_workorder.id if source_workorder else record.x_rework_source_workorder_id.id,
                'x_rework_exit_workorder_id': source_workorder.id if source_workorder else record.x_rework_exit_workorder_id.id,
            })

    def _mark_rework_step_passed(self, workorder):
        for record in self:
            if not record._workorder_in_current_rework_window(workorder):
                continue
            exit_workorder = record.x_rework_exit_workorder_id or record.x_rework_source_workorder_id
            if exit_workorder and workorder == exit_workorder:
                record.write({
                    'x_mes_repair_state': 'none',
                    'x_rework_source_workorder_id': False,
                    'x_rework_entry_workorder_id': False,
                    'x_rework_exit_workorder_id': False,
                })

    def action_apply_business_state(self, state, workorder=False, operator_code=None, note=None):
        workorder = self._resolve_workorder_arg(workorder)
        result = super().action_apply_business_state(
            state,
            workorder=workorder,
            operator_code=operator_code,
            note=note,
        )
        if not note or not workorder:
            return result
        for record in self:
            event_result = self._result_for_state(state)
            self.env['sn.wsd.mes.sn.travel'].record_event(
                serial_number=record.serial_no,
                event_type='complete',
                workcenter_code=workorder.x_mes_workcenter_id.code if workorder.x_mes_workcenter_id else False,
                workorder_id=workorder.id,
                production_id=workorder.production_id.id,
                result=event_result,
                operator_code=operator_code,
                note=note,
            )
        return result
