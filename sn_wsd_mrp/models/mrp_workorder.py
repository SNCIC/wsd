from odoo import api, fields, models, _


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    qty_remaining = fields.Float(string='Quantity To Produce')
    qty_ready = fields.Float(string='WIP Quantity')

    _METER_OPERATION_KEYWORDS = {
        'parameter_write': ('parameter', 'para'),
        'initial_calibration': ('calibration',),
        'aging_unload': ('aging_unload', 'unload'),
        'aging_load': ('aging_load', 'load'),
        'reflow': ('reflow',),
        'aoi': ('aoi',),
        'ict': ('ict',),
        'fct': ('fct',),
        'pcb_assembly': ('pcb', 'board'),
        'pcb_repair': ('pcb_repair', 'board_repair'),
        'hipot': ('hipot',),
        'communication_test': ('communication', 'comm'),
        'sealing': ('seal',),
        'packing': ('pack',),
        'verification': ('verify', 'verification'),
        'firmware': ('firmware', 'program', 'burn'),
        'assembly': ('assembly',),
        'smt': ('smt',),
        'dip': ('dip',),
    }

    x_is_smt_operation = fields.Boolean(
        string='Is SMT Operation',
        compute='_compute_x_operation_visibility',
    )
    x_is_meter_operation = fields.Boolean(
        string='Is Meter Operation',
        compute='_compute_x_operation_visibility',
    )

    x_meter_operation_type = fields.Selection(
        [
            ('smt', 'SMT'),
            ('dip', 'DIP'),
            ('reflow', 'Reflow'),
            ('aoi', 'AOI'),
            ('ict', 'ICT'),
            ('fct', 'FCT'),
            ('pcb_assembly', 'PCB Assembly'),
            ('pcb_repair', 'PCB Repair'),
            ('assembly', 'Assembly'),
            ('firmware', 'Firmware'),
            ('parameter_write', 'Parameter Write'),
            ('initial_calibration', 'Initial Calibration'),
            ('aging_load', 'Aging Load'),
            ('aging_unload', 'Aging Unload'),
            ('verification', 'Verification'),
            ('hipot', 'Hipot'),
            ('communication_test', 'Communication Test'),
            ('sealing', 'Sealing'),
            ('packing', 'Packing'),
        ],
        string='Meter Operation Type',
        index=True,
    )
    x_route_operation_id = fields.Many2one(
        'sn.wsd.process.route.operation',
        string='Route Operation',
        related='operation_id.x_route_operation_id',
        store=True,
        readonly=True,
        index=True,
    )
    x_manufacturing_batch_id = fields.Many2one(
        'sn.wsd.manufacturing.batch',
        string='Manufacturing Batch',
        related='production_id.x_manufacturing_batch_id',
        store=True,
        readonly=True,
        index=True,
        check_company=True,
    )
    x_batch_operation_snapshot_id = fields.Many2one(
        'sn.wsd.manufacturing.batch.operation',
        string='Batch Operation Snapshot',
        compute='_compute_x_batch_operation_snapshot_id',
        store=True,
        readonly=True,
        index=True,
        check_company=True,
    )
    x_meter_equipment_id = fields.Many2one('maintenance.equipment', string='Meter Equipment', check_company=True)
    x_meter_workcenter_id = fields.Many2one('mrp.workcenter', string='Meter Work Center', check_company=True)
    x_meter_workshop_id = fields.Many2one('sn.mrp.workshop', string='Workshop', check_company=True)
    x_meter_production_line_id = fields.Many2one('sn.mrp.production.line', string='Production Line', check_company=True)
    x_meter_workcenter_code = fields.Char(string='Station Code')
    x_meter_fixture_id = fields.Char(string='Fixture')
    x_meter_operator_code = fields.Char(string='Operator Code')
    x_meter_shift_code = fields.Char(string='Shift Code')
    x_meter_qty_input = fields.Float(string='Input Qty')
    x_meter_qty_pass = fields.Float(string='Pass Qty')
    x_meter_qty_fail = fields.Float(string='Fail Qty')
    x_meter_qty_rework = fields.Float(string='Rework Qty')
    x_meter_qty_scrap = fields.Float(string='Scrap Qty')
    x_program_version = fields.Char(string='Program Version')
    x_parameter_version = fields.Char(string='Parameter Version')
    x_calibration_recipe = fields.Char(string='Calibration Recipe')
    x_aging_hours_planned = fields.Float(string='Aging Hours Planned')
    x_aging_hours_actual = fields.Float(string='Aging Hours Actual')
    x_test_profile = fields.Char(string='Test Profile')
    x_exception_flag = fields.Boolean(string='Exception')
    x_exception_type = fields.Char(string='Exception Type')
    x_exception_note = fields.Text(string='Exception Note')
    x_internal_serial_ids = fields.One2many('sn.wsd.internal.serial', 'current_workorder_id', string='Current Internal Serials')
    x_meter_pack_record_ids = fields.One2many('sn.wsd.meter.pack.record', 'pack_workorder_id', string='Pack Records')
    x_meter_aging_batch_ids = fields.One2many('sn.wsd.meter.aging.batch', 'workorder_id', string='Aging Batches')

    @api.depends('x_meter_operation_type')
    def _compute_x_operation_visibility(self):
        for workorder in self:
            workorder.x_is_smt_operation = workorder.x_meter_operation_type in ('smt', 'dip')
            workorder.x_is_meter_operation = bool(workorder.x_meter_operation_type)

    @api.depends('x_manufacturing_batch_id.operation_snapshot_ids', 'x_route_operation_id')
    def _compute_x_batch_operation_snapshot_id(self):
        for workorder in self:
            snapshot = self.env['sn.wsd.manufacturing.batch.operation']
            if workorder.x_manufacturing_batch_id and workorder.x_route_operation_id:
                snapshot = workorder.x_manufacturing_batch_id.operation_snapshot_ids.filtered(
                    lambda operation: operation.route_operation_id == workorder.x_route_operation_id
                )[:1]
            workorder.x_batch_operation_snapshot_id = snapshot

    @api.model
    def _infer_meter_operation_type(self, station=False, operation=False):
        text_parts = [
            operation.x_step_code if operation else False,
            operation.name if operation else False,
            station.code if station else False,
            station.name if station else False,
        ]
        haystack = ' '.join(filter(None, text_parts)).lower()

        for operation_type in (
            'parameter_write',
            'initial_calibration',
            'aging_unload',
            'aging_load',
            'reflow',
            'aoi',
            'ict',
            'fct',
            'pcb_assembly',
            'pcb_repair',
            'hipot',
            'communication_test',
            'sealing',
            'packing',
            'verification',
            'firmware',
            'assembly',
            'smt',
            'dip',
        ):
            if any(keyword in haystack for keyword in self._METER_OPERATION_KEYWORDS[operation_type]):
                return operation_type

        return False

    def _find_route_operation(self):
        self.ensure_one()
        if not self.production_id.bom_id or not self.x_mes_workcenter_id:
            return self.env['mrp.routing.workcenter']
        return self.env['mrp.routing.workcenter'].search([
            ('bom_id', '=', self.production_id.bom_id.id),
            ('workcenter_id', '=', self.x_mes_workcenter_id.id),
        ], order='sequence asc, id asc', limit=1)

    def _sync_meter_operation_context(self, force=False):
        for workorder in self:
            values = {}
            expected_operation = self.env['mrp.routing.workcenter']
            if workorder.production_id.bom_id and workorder.x_mes_workcenter_id:
                expected_operation = workorder._find_route_operation()
                if expected_operation and (force or workorder.operation_id != expected_operation):
                    values['operation_id'] = expected_operation.id
            operation_type = workorder._infer_meter_operation_type(
                station=workorder.x_mes_workcenter_id,
                operation=expected_operation or workorder.operation_id,
            )
            if operation_type and (force or workorder.x_meter_operation_type != operation_type):
                values['x_meter_operation_type'] = operation_type
            if values:
                workorder.with_context(skip_meter_context_sync=True).write(values)

    def _inherit_meter_execution_defaults(self):
        for workorder in self:
            if not workorder.production_id or not workorder.x_meter_operation_type:
                continue
            if workorder.x_meter_equipment_id and workorder.x_meter_operator_code:
                continue
            template = self.search([
                ('id', '!=', workorder.id),
                ('production_id', '!=', False),
                ('production_id.product_id', '=', workorder.production_id.product_id.id),
                ('x_meter_operation_type', '=', workorder.x_meter_operation_type),
                ('x_mes_workcenter_id', '=', workorder.x_mes_workcenter_id.id),
                ('x_meter_equipment_id', '!=', False),
            ], order='id desc', limit=1)
            if not template:
                continue
            values = {}
            for field_name in (
                'x_meter_equipment_id',
                'x_meter_workcenter_id',
                'x_meter_workshop_id',
                'x_meter_production_line_id',
                'x_meter_workcenter_code',
                'x_meter_fixture_id',
                'x_meter_operator_code',
                'x_meter_shift_code',
                'x_program_version',
                'x_parameter_version',
                'x_calibration_recipe',
                'x_aging_hours_planned',
                'x_test_profile',
            ):
                if not workorder[field_name] and template[field_name]:
                    values[field_name] = template[field_name].id if template._fields[field_name].type == 'many2one' else template[field_name]
            if values:
                workorder.with_context(skip_meter_context_sync=True).write(values)

    def action_sync_meter_context(self):
        self._sync_meter_operation_context(force=True)
        return True

    @api.onchange('x_meter_equipment_id')
    def _onchange_x_meter_equipment_id(self):
        for workorder in self:
            equipment = workorder.x_meter_equipment_id
            if not equipment:
                continue
            station = equipment.x_mes_workcenter_id
            workorder.x_meter_workcenter_id = station
            workorder.x_mes_workcenter_id = station
            workorder.x_meter_workshop_id = station.x_workshop_id if station else False
            workorder.x_meter_production_line_id = station.x_production_line_id if station else False
            workorder.x_meter_workcenter_code = station.code if station else False
            if equipment.x_mes_workcenter_id:
                workorder.workcenter_id = equipment.x_mes_workcenter_id
            route_operation = workorder._find_route_operation()
            if route_operation:
                workorder.operation_id = route_operation
            workorder.x_meter_operation_type = workorder._infer_meter_operation_type(
                station=workorder.x_mes_workcenter_id,
                operation=route_operation or workorder.operation_id,
            )

    @api.onchange('workcenter_id')
    def _onchange_workcenter_id_sync_meter_station(self):
        for workorder in self:
            if workorder.x_meter_equipment_id and workorder.x_meter_equipment_id.x_mes_workcenter_id == workorder.workcenter_id:
                continue
            station = workorder.x_meter_workcenter_id if workorder.x_meter_workcenter_id == workorder.workcenter_id else self.env['mrp.workcenter']
            if not station and workorder.workcenter_id and workorder.x_meter_production_line_id:
                station = self.env['mrp.workcenter'].search([
                    ('id', '=', workorder.workcenter_id.id),
                    ('x_production_line_id', '=', workorder.x_meter_production_line_id.id),
                ], limit=1)
            if not station and workorder.workcenter_id:
                station = workorder.workcenter_id
            workorder.x_meter_workcenter_id = station
            workorder.x_mes_workcenter_id = station
            workorder.x_meter_workshop_id = station.x_workshop_id if station else False
            workorder.x_meter_production_line_id = station.x_production_line_id if station else False
            workorder.x_meter_workcenter_code = station.code if station else False
            route_operation = workorder._find_route_operation()
            if route_operation:
                workorder.operation_id = route_operation
            workorder.x_meter_operation_type = workorder._infer_meter_operation_type(
                station=workorder.x_mes_workcenter_id,
                operation=route_operation or workorder.operation_id,
            )

    def write(self, vals):
        if 'qty_produced' in vals:
            return super().write(vals)
        should_sync_meter_context = (
            not self.env.context.get('skip_meter_context_sync')
            and bool({
                'production_id',
                'operation_id',
                'workcenter_id',
                'x_mes_workcenter_id',
                'x_meter_workcenter_id',
                'x_meter_operation_type',
            }.intersection(vals))
        )
        result = super().write(vals)
        if should_sync_meter_context:
            self._sync_meter_operation_context()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        workorders = super().create(vals_list)
        workorders._sync_meter_operation_context()
        workorders._inherit_meter_execution_defaults()
        return workorders

    def button_start(self, raise_on_invalid_state=False):
        productions = self.mapped('production_id').filtered(lambda production: production.state not in ('done', 'cancel'))
        productions._check_can_go_online()
        result = super().button_start(raise_on_invalid_state=raise_on_invalid_state)
        productions.filtered(lambda production: production.x_online_state != 'online').action_set_online()
        return result

    def _meter_get_or_create_serial_archive(self, serial_number):
        self.ensure_one()
        archive = self.env['sn.wsd.internal.serial'].search([
            ('serial_no', '=', serial_number),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        values = {
            'serial_no': serial_number,
            'barcode': serial_number,
            'product_id': self.product_id.id,
            'production_id': self.production_id.id,
            'manufacturing_batch_id': self.x_manufacturing_batch_id.id,
            'company_id': self.company_id.id,
            'current_workorder_id': self.id,
            'current_operation_id': self.operation_id.id,
            'current_workcenter_id': self.workcenter_id.id,
            'customer_batch_no': self.production_id.x_delivery_batch_no,
            'firmware_version': self.production_id.x_firmware_version,
            'parameter_version': self.production_id.x_parameter_template,
            'current_production_id': self.production_id.id,
        }
        if archive:
            archive.write(values)
        else:
            archive = self.env['sn.wsd.internal.serial'].create(values)
        return archive

    def _meter_apply_aging_transition(self, archive, operator_code=None, note=None, batch=None, slot_no=None, unload=False):
        self.ensure_one()
        if unload:
            batch = batch or archive.current_aging_batch_id or self.x_meter_aging_batch_ids.filtered(lambda b: b.status in ('loaded', 'aging'))[:1]
            if batch:
                line = batch.line_ids.filtered(lambda l: l.serial_id == archive)[:1]
                if line:
                    line.write({
                        'unload_time': fields.Datetime.now(),
                        'result': 'pass',
                    })
                archive.write({
                    'aging_result': 'pass',
                    'current_aging_batch_id': False,
                })
                if all(batch.line_ids.mapped('unload_time')):
                    batch.action_finish()
            return
        batch = batch or self.x_meter_aging_batch_ids.filtered(lambda b: b.status in ('draft', 'loaded', 'aging'))[:1]
        if not batch:
            batch = self.env['sn.wsd.meter.aging.batch'].create({
                'production_id': self.production_id.id,
                'workorder_id': self.id,
                'equipment_id': self.x_meter_equipment_id.id,
                'aging_cart_no': self.x_meter_fixture_id or self.name,
                'planned_hours': self.x_aging_hours_planned or 8.0,
                'operator_code': operator_code,
                'status': 'loaded',
            })
        line = batch.line_ids.filtered(lambda l: l.serial_id == archive)[:1]
        if not line:
            self.env['sn.wsd.meter.aging.batch.line'].create({
                'batch_id': batch.id,
                'serial_id': archive.id,
                'slot_no': slot_no or archive.serial_no,
                'load_time': fields.Datetime.now(),
                'note': note,
            })
        archive.write({
            'current_aging_batch_id': batch.id,
        })
        if batch.status == 'draft':
            batch.status = 'loaded'

    def _meter_apply_pack_transition(self, archive, operator_code=None, note=None, seal_no=None, carton_no=None, pallet_no=None):
        self.ensure_one()
        archive.check_packaging_readiness()
        carton_package = self.env['stock.package']
        if carton_no:
            carton_package = self.env['stock.package'].get_or_create_wsd_package(
                carton_no,
                'carton',
                self.company_id,
                x_wsd_production_id=self.production_id,
                x_wsd_manufacturing_batch_id=self.x_manufacturing_batch_id,
                x_wsd_operator_code=operator_code,
            )
        existing = self.x_meter_pack_record_ids.filtered(lambda p: p.serial_id == archive)[:1]
        values = {
            'serial_id': archive.id,
            'production_id': self.production_id.id,
            'pack_workorder_id': self.id,
            'seal_no': seal_no or archive.seal_no,
            'carton_no': carton_package.name or carton_no or archive.carton_no,
            'pallet_no': carton_package.parent_package_id.name or archive.pallet_no,
            'carton_package_id': carton_package.id,
            'pallet_package_id': carton_package.parent_package_id.id,
            'operator_code': operator_code,
            'note': note,
        }
        if existing:
            existing.write(values)
            existing.action_apply_to_serial()
        else:
            self.env['sn.wsd.meter.pack.record'].create(values).action_apply_to_serial()
        self._meter_sync_packed_production_quantities()

    def _meter_sync_packed_production_quantities(self):
        for workorder in self:
            production = workorder.production_id
            if not production or not production.product_id:
                continue
            archives = self.env['sn.wsd.internal.serial'].search([
                ('production_id', '=', production.id),
                ('product_id', '=', production.product_id.id),
                ('pack_date', '!=', False),
            ])
            target_qty = production.product_uom_id.round(min(len(archives), production.product_qty))
            production.write({
                'qty_producing': target_qty,
            })
            ratio = target_qty / production.product_qty if production.product_qty else 0.0
            for move in production.move_raw_ids.filtered(lambda item: item.state not in ('done', 'cancel')):
                move_qty = move.product_uom.round(move.product_uom_qty * ratio)
                move._set_quantity_done(move_qty)
                move.picked = bool(move_qty)
            for move in production.move_finished_ids.filtered(lambda item: item.product_id == production.product_id and item.state not in ('done', 'cancel')):
                move._set_quantity_done(target_qty)
                move.picked = bool(target_qty)

    def action_meter_sync_packed_production_quantities(self):
        self._meter_sync_packed_production_quantities()
        return True

