from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        compute='_compute_x_mes_order_id',
        readonly=True,
        check_company=True,
    )
    x_customer_id = fields.Many2one(
        'res.partner',
        string='Source Customer',
        compute='_compute_x_customer_id',
        store=False,
    )
    x_customer_display_name = fields.Char(
        string='Customer',
        compute='_compute_x_customer_id',
        store=False,
    )
    x_actual_start_date = fields.Date(
        string='Actual Start Date',
        compute='_compute_x_production_actual_dates',
        store=True,
    )
    x_actual_finished_date = fields.Date(
        string='Actual Completion Date',
        compute='_compute_x_production_actual_dates',
        store=True,
    )
    x_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route (Independent)',
        copy=True,
        tracking=True,
        help='Independent route snapshot; no longer derived from the BOM.',
    )

    @api.onchange('product_id')
    def _onchange_x_route_id_from_drawing_no(self):
        # The route is resolved through the product's 图号 (drawing number):
        # MO 图号 -> route drawing bindings -> current released route. Seed
        # x_route_id from that match, but only when it is empty so a
        # manually chosen route is preserved.
        for production in self:
            if production.x_route_id:
                continue
            route = self.env['sn.wsd.process.route']._find_current_route_by_drawing_no(
                production.product_id.default_code, production.company_id.id)
            if route:
                production.x_route_id = route

    @api.model_create_multi
    def create(self, vals_list):
        productions = super().create(vals_list)
        # Snapshot the current effective route for the product's 图号 into
        # x_route_id at creation (unless explicitly set). The onchange only
        # fires from the UI form, so programmatic creation (import, ...)
        # needs this explicit seeding.
        for production in productions:
            if not production.x_route_id:
                route = self.env['sn.wsd.process.route']._find_current_route_by_drawing_no(
                    production.product_id.default_code, production.company_id.id)
                if route:
                    production.x_route_id = route
        return productions

    x_is_eip_material = fields.Boolean(
        string='EIP',
        related='product_id.is_eip_material',
        store=True,
        readonly=True,
    )
    x_is_nqi_material = fields.Boolean(
        string='NQI',
        related='product_id.is_nqi_material',
        store=True,
        readonly=True,
    )
    x_has_smt_operations = fields.Boolean(
        string='Has SMT Operations',
        compute='_compute_x_operation_visibility',
    )
    x_has_meter_operations = fields.Boolean(
        string='Has Meter Operations',
        compute='_compute_x_operation_visibility',
    )
    x_workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        compute='_compute_x_process_scope',
        store=True,
        readonly=False,
        precompute=True,
        check_company=True,
        tracking=True,
        index=True,
    )
    x_online_state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('online', 'Online'),
            ('offline', 'Offline'),
        ],
        string='Online Stage',
        default='draft',
        copy=False,
        tracking=True,
        index=True,
    )

    x_meter_product_type = fields.Selection(
        [
            ('single_phase', 'Single Phase'),
            ('three_phase', 'Three Phase'),
            ('collector', 'Collector'),
            ('terminal', 'Terminal'),
            ('other', 'Other'),
        ],
        string='Meter Product Type',
    )
    x_meter_model = fields.Char(string='Meter Model')
    x_voltage_spec = fields.Char(string='Voltage Spec')
    x_current_spec = fields.Char(string='Current Spec')
    x_accuracy_class = fields.Char(string='Accuracy Class')
    x_comm_protocol = fields.Char(string='Communication Protocol')
    x_firmware_version = fields.Char(string='Firmware Version')
    x_parameter_template = fields.Char(string='Parameter Template')
    x_inspection_standard = fields.Char(string='Inspection Standard')
    x_customer_project = fields.Char(string='Customer Project')
    x_tender_no = fields.Char(string='Tender No.')
    x_contract_no = fields.Char(string='Contract No.')
    x_production_batch_no = fields.Char(string='Production Batch No.')
    x_delivery_batch_no = fields.Char(string='Delivery Batch No.')
    x_need_burn_firmware = fields.Boolean(string='Need Firmware Burning', default=True)
    x_need_initial_calibration = fields.Boolean(string='Need Initial Calibration', default=True)
    x_need_aging = fields.Boolean(string='Need Aging', default=True)
    x_need_final_verification = fields.Boolean(string='Need Final Verification', default=True)
    x_need_sealing = fields.Boolean(string='Need Sealing', default=True)
    x_need_carton_traceability = fields.Boolean(string='Need Carton Traceability', default=True)
    x_meter_flow_state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('material_ready', 'Material Ready'),
            ('pcba_done', 'PCBA Done'),
            ('assembly_done', 'Assembly Done'),
            ('burned', 'Burned'),
            ('initial_calibrated', 'Initial Calibrated'),
            ('aging', 'Aging'),
            ('aging_done', 'Aging Done'),
            ('verified', 'Verified'),
            ('sealed', 'Sealed'),
            ('packed', 'Packed'),
            ('done', 'Done'),
        ],
        string='Meter Flow State',
        default='draft',
        tracking=True,
    )
    x_internal_serial_ids = fields.One2many('sn.wsd.internal.serial', 'production_id', string='Origin Internal Serials')
    x_internal_serial_count = fields.Integer(compute='_compute_internal_serial_stats')
    x_internal_serial_passed = fields.Integer(compute='_compute_internal_serial_stats')
    x_internal_serial_failed = fields.Integer(compute='_compute_internal_serial_stats')
    x_internal_serial_scrapped = fields.Integer(compute='_compute_internal_serial_stats')
    x_meter_aging_batch_ids = fields.One2many('sn.wsd.meter.aging.batch', 'production_id', string='Aging Batches')
    x_meter_aging_batch_count = fields.Integer(compute='_compute_internal_serial_stats')
    x_meter_pack_record_ids = fields.One2many('sn.wsd.meter.pack.record', 'production_id', string='Pack Records')
    x_meter_pack_record_count = fields.Integer(compute='_compute_internal_serial_stats')

    @api.depends('x_mes_order_ids.state', 'x_mes_order_ids.date_plan')
    def _compute_x_mes_order_id(self):
        for production in self:
            orders = production.x_mes_order_ids.filtered(
                lambda order: order.state != 'cancelled'
            ).sorted(lambda order: (order.date_plan, order.id))
            production.x_mes_order_id = orders[:1]

    def _get_active_stage_serials(self):
        self.ensure_one()
        serials = self.env['sn.wsd.internal.serial'].with_context(active_test=False).search([
            ('production_id', '=', self.id),
            ('active', '=', True),
        ])
        return serials.filtered(lambda serial: not serial.is_confirmed_scrapped())

    def _get_serial_capacity(self):
        self.ensure_one()
        planned_qty = int(self.product_uom_id.round(self.product_qty))
        all_serials = self.env['sn.wsd.internal.serial'].with_context(active_test=False).search([
            ('production_id', '=', self.id),
        ])
        active_serials = all_serials.filtered(lambda serial: serial.active and not serial.is_confirmed_scrapped())
        scrapped_serials = all_serials.filtered(lambda serial: serial.is_confirmed_scrapped())
        return {
            'planned_qty': planned_qty,
            'active_serial_qty': len(active_serials),
            'scrapped_serial_qty': len(scrapped_serials),
            'historical_serial_qty': len(all_serials),
            'available_qty': max(planned_qty - len(active_serials), 0),
        }

    def _lock_serial_capacity(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM mrp_production WHERE id = %s FOR UPDATE', [self.id])

    def _get_or_create_stage_lot(self, serial_no, identity=False):
        self.ensure_one()
        lot = self.env['stock.lot'].with_context(active_test=False).search([
            ('name', '=', serial_no),
            ('product_id', '=', self.product_id.id),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not lot:
            lot = self.env['stock.lot'].create({
                'name': serial_no,
                'product_id': self.product_id.id,
                'company_id': self.company_id.id,
                'x_serial_identity_id': identity.id if identity else False,
            })
        elif identity and not lot.x_serial_identity_id:
            lot.x_serial_identity_id = identity
        return lot

    def _find_serial_source(self, serial_no):
        self.ensure_one()
        source_serial = self.env['sn.wsd.internal.serial'].with_context(active_test=False).search([
            ('serial_no', '=', serial_no),
            ('company_id', '=', self.company_id.id),
            ('production_id', '!=', self.id),
            ('active', '=', True),
        ], order='production_date desc, id desc', limit=1)
        source_lot = source_serial.lot_id or self.env['stock.lot'].with_context(active_test=False).search([
            ('name', '=', serial_no),
            ('product_id', '!=', self.product_id.id),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.company_id.id),
        ], order='id desc', limit=1)
        return source_serial, source_lot

    def get_or_create_stage_serial(self, serial_no, workorder=False, allow_create=False, origin_type='external'):
        self.ensure_one()
        serial_no = (serial_no or '').strip()
        if not serial_no:
            raise ValidationError(_('Serial number is required.'))
        serial_model = self.env['sn.wsd.internal.serial'].with_context(active_test=False)
        serial = serial_model.search([
            ('serial_no', '=', serial_no),
            ('company_id', '=', self.company_id.id),
            ('production_id', '=', self.id),
        ], limit=1)
        if serial:
            if not serial.active:
                raise ValidationError(_('Serial number %s is inactive.') % serial_no)
            return serial, False
        if not allow_create:
            return serial, False

        self._lock_serial_capacity()
        serial = serial_model.search([
            ('serial_no', '=', serial_no),
            ('company_id', '=', self.company_id.id),
            ('production_id', '=', self.id),
        ], limit=1)
        if serial:
            return serial, False
        capacity = self._get_serial_capacity()
        if capacity['available_qty'] <= 0:
            raise ValidationError(_(
                'Serial capacity exceeded for manufacturing order %(production)s. '
                'Planned: %(planned)s, active: %(active)s, scrapped: %(scrapped)s.'
            ) % {
                'production': self.display_name,
                'planned': capacity['planned_qty'],
                'active': capacity['active_serial_qty'],
                'scrapped': capacity['scrapped_serial_qty'],
            })

        source_serial, source_lot = self._find_serial_source(serial_no)
        identity = source_serial.serial_identity_id or source_lot.x_serial_identity_id
        if not identity:
            identity = self.env['sn.wsd.serial.identity'].get_or_create(
                serial_no,
                self.company_id,
                origin_type=origin_type,
                origin_production_id=source_serial.production_id or self,
                origin_lot_id=source_lot,
            )
        lot = self._get_or_create_stage_lot(serial_no, identity=identity)
        scrapped_candidate = serial_model.search([
            ('production_id', '=', self.id),
            ('final_result', '=', 'scrap'),
            ('replacement_serial_ids', '=', False),
        ], order='production_date, id', limit=1)
        serial = serial_model.create({
            'serial_no': serial_no,
            'barcode': serial_no,
            'serial_identity_id': identity.id,
            'product_id': self.product_id.id,
            'production_id': self.id,
            'current_production_id': self.id,
            'company_id': self.company_id.id,
            'serial_type': 'finished' if self.x_has_meter_operations else 'semifinished',
            'parent_id': source_serial.id,
            'source_lot_id': source_lot.id,
            'lot_id': lot.id,
            'entry_route_operation_id': workorder.operation_id.x_route_operation_id.id if workorder and workorder.operation_id.x_route_operation_id else False,
            'entry_time': fields.Datetime.now(),
            'replaces_serial_id': scrapped_candidate.id,
            'identity_origin_type': origin_type,
        })
        if lot not in self.lot_producing_ids:
            self.lot_producing_ids = [fields.Command.link(lot.id)]
        return serial, True
    @api.depends(
        'state',
        'reservation_state',
        'date_start',
        'move_raw_ids',
        'move_raw_ids.state',
        'move_raw_ids.forecast_availability',
        'move_raw_ids.forecast_expected_date',
    )
    def _compute_components_availability(self):
        super()._compute_components_availability()
        productions = self.filtered(lambda production: production.state not in ('cancel', 'done', 'draft'))
        if not productions:
            return

        open_raw_moves = productions.move_raw_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
        open_raw_moves._fields['forecast_availability'].compute_value(open_raw_moves)
        for production in productions:
            raw_moves = production.move_raw_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
            production.components_availability_state = 'available'
            production.components_availability = _('Available')
            if any(
                move.product_id
                and move.product_id.uom_id.compare(
                    move.forecast_availability,
                    0 if move.state == 'draft' else move.product_qty,
                ) == -1
                for move in raw_moves
            ):
                production.components_availability = _('Not Available')
                production.components_availability_state = 'unavailable'
            else:
                forecast_date = max(raw_moves.filtered('forecast_expected_date').mapped('forecast_expected_date'), default=False)
                if forecast_date:
                    production.components_availability = _('Exp %s', format_date(self.env, forecast_date))
                    if production.date_start:
                        production.components_availability_state = 'late' if forecast_date > production.date_start else 'expected'

    @api.depends('reference_ids', 'move_dest_ids')
    def _compute_x_customer_id(self):
        for production in self:
            customer = self.env['res.partner']
            if 'sale_line_id' in production._fields:
                customer = production.sale_line_id.order_partner_id
            if not customer and 'sale_ids' in production.reference_ids._fields:
                reference_customers = production.reference_ids.sale_ids.partner_id
                if len(reference_customers) == 1:
                    customer = reference_customers
            if not customer:
                sale_lines = production.move_dest_ids.filtered(lambda move: 'sale_line_id' in move._fields).sale_line_id
                destination_customers = sale_lines.order_partner_id
                if len(destination_customers) == 1:
                    customer = destination_customers
            production.x_customer_id = customer
            production.x_customer_display_name = customer.x_customer_alias or customer.name

    @api.depends(
        'state',
        'date_start',
        'date_finished',
    )
    def _compute_x_production_actual_dates(self):
        for production in self:
            start_times = [production.date_start] if production.date_start else []
            end_times = [production.date_finished] if production.date_finished else []
            production.x_actual_start_date = fields.Date.to_date(min(start_times)) if start_times else False
            production.x_actual_finished_date = fields.Date.to_date(max(end_times)) if end_times else False

    @api.depends('x_mes_order_ids.x_route_operation_ids.operation_id.x_station_type')
    def _compute_x_operation_visibility(self):
        smt_operation_types = {'smt', 'dip', 'reflow', 'aoi', 'ict', 'fct', 'pcb_assembly', 'pcb_repair'}
        for production in self:
            operation_types = set(
                production.x_mes_order_ids.x_route_operation_ids.mapped(
                    'operation_id.x_station_type'
                )
            )
            production.x_has_smt_operations = bool(operation_types.intersection(smt_operation_types))
            production.x_has_meter_operations = bool(operation_types.difference(smt_operation_types))

    @api.depends(
        'bom_id',
        'bom_id.x_workshop_id',
    )
    def _compute_x_process_scope(self):
        for production in self:
            bom = production.bom_id
            if not bom:
                production.x_workshop_id = False
                continue
            production.x_workshop_id = bom.x_workshop_id

    @api.depends(
        'picking_type_id',
        'x_workshop_id',
        'x_workshop_id.component_location_id',
        'x_workshop_id.finished_product_location_id',
    )
    def _compute_locations(self):
        preserved_locations = {
            production.id: (production.location_src_id, production.location_dest_id)
            for production in self
            if production.id and production.state != 'draft'
        }
        super()._compute_locations()
        for production in self.filtered(lambda record: record.id in preserved_locations):
            production.location_src_id, production.location_dest_id = preserved_locations[production.id]
        self.filtered(lambda production: production.state == 'draft')._apply_workshop_manufacturing_locations()

    def _apply_workshop_manufacturing_locations(self):
        for production in self:
            warehouse = production.picking_type_id.warehouse_id
            workshop = production.x_workshop_id
            if not warehouse or not workshop:
                continue
            # The MO always consumes from the workshop line-side location,
            # whatever the step mode: with one-step manufacturing no native
            # picking is created at confirm (material requisitions are issued
            # from the MES orders instead), with multi-step the workshop
            # locations keep feeding the native chain.
            if workshop.component_location_id:
                production.location_src_id = workshop.component_location_id
            if warehouse.manufacture_steps == 'pbm_sam' and workshop.finished_product_location_id:
                production.location_dest_id = workshop.finished_product_location_id

    def _check_workshop_manufacturing_locations(self):
        for production in self:
            warehouse = production.picking_type_id.warehouse_id
            if not warehouse or warehouse.manufacture_steps == 'mrp_one_step':
                continue
            workshop = production.x_workshop_id
            if not workshop:
                raise ValidationError(_(
                    "A workshop must be selected before confirming the multi-step manufacturing order '%s'.",
                    production.display_name,
                ))
            component_location = workshop.component_location_id
            if not component_location:
                raise ValidationError(_(
                    "A component location must be configured for workshop '%s' before confirming a two-step or three-step manufacturing order.",
                    workshop.display_name,
                ))
            production._check_workshop_location(
                component_location,
                warehouse.pbm_loc_id,
                _('component'),
                _('pre-production'),
            )
            if warehouse.manufacture_steps != 'pbm_sam':
                continue
            finished_product_location = workshop.finished_product_location_id
            if not finished_product_location:
                raise ValidationError(_(
                    "A finished product location must be configured for workshop '%s' before confirming a three-step manufacturing order.",
                    workshop.display_name,
                ))
            production._check_workshop_location(
                finished_product_location,
                warehouse.sam_loc_id,
                _('finished product'),
                _('post-production'),
            )

    def _check_workshop_location(self, location, parent_location, location_label, parent_label):
        self.ensure_one()
        if not location.active:
            raise ValidationError(_(
                "The %(location_label)s location '%(location)s' of workshop '%(workshop)s' must be active.",
                location_label=location_label,
                location=location.display_name,
                workshop=self.x_workshop_id.display_name,
            ))
        if location.company_id != self.company_id:
            raise ValidationError(_(
                "The %(location_label)s location '%(location)s' of workshop '%(workshop)s' must belong to the manufacturing order company.",
                location_label=location_label,
                location=location.display_name,
                workshop=self.x_workshop_id.display_name,
            ))
        if not parent_location or location == parent_location or not location._child_of(parent_location):
            raise ValidationError(_(
                "The %(location_label)s location of workshop '%(workshop)s' must be located under the %(parent_label)s location '%(parent_location)s'.",
                location_label=location_label,
                workshop=self.x_workshop_id.display_name,
                parent_label=parent_label,
                parent_location=parent_location.display_name if parent_location else '-',
            ))

    @api.onchange('bom_id')
    def _onchange_bom_id_sync_process_scope(self):
        for production in self:
            production._compute_x_process_scope()

    # NOTE: the production line no longer lives on the MO — it is a
    # scheduling dimension carried by the MES orders (制令单). Online gating
    # and uniqueness are therefore workshop-scoped only.

    @api.constrains('x_online_state', 'x_workshop_id', 'company_id')
    def _check_single_online_order_per_workshop(self):
        for production in self:
            if production.x_online_state != 'online' or not production.x_workshop_id:
                continue
            existing = self.search([
                ('id', '!=', production.id),
                ('company_id', '=', production.company_id.id),
                ('x_online_state', '=', 'online'),
                ('x_workshop_id', '=', production.x_workshop_id.id),
                ('state', 'not in', ['done', 'cancel']),
            ], limit=1)
            if existing:
                raise ValidationError(_(
                    'Only one manufacturing order can be online for the same workshop. Current online order: %s'
                ) % existing.display_name)

    def _check_can_go_online(self):
        for production in self:
            if not production.x_workshop_id:
                raise ValidationError(_('Set the workshop before putting the manufacturing order online.'))
            existing = self.search([
                ('id', '!=', production.id),
                ('company_id', '=', production.company_id.id),
                ('x_online_state', '=', 'online'),
                ('x_workshop_id', '=', production.x_workshop_id.id),
                ('state', 'not in', ['done', 'cancel']),
            ], limit=1)
            if existing:
                raise ValidationError(_(
                    'Only one manufacturing order can be online for the same workshop. Current online order: %s'
                ) % existing.display_name)

    def action_set_online(self):
        self._check_can_go_online()
        self.write({'x_online_state': 'online'})
        return True

    def action_set_offline(self):
        self.write({'x_online_state': 'offline'})
        return True

    def action_cancel(self):
        res = super().action_cancel()
        # cascade: cancelling the MO revokes its still-released MES orders
        # (partially issued batches included, same policy as force close)
        released_orders = self.x_mes_order_ids.filtered(
            lambda order: order.state == 'released')
        if released_orders:
            released_orders.with_context(mes_force_cancel=True).action_cancel()
        return res

    def action_force_close(self):
        """Manual bail-out: close the MO with what actually happened.

        Approved flow (强制关闭): revoke the still-released MES orders
        (issued partial batches included, their pickings stay on the books),
        keep the real consumption / production quantities, void the remaining
        demand WITHOUT creating backorders, then mark the MO done.
        """
        for production in self:
            if production.state in ('done', 'cancel'):
                raise UserError(_(
                    'Only open manufacturing orders can be force closed: %s',
                    production.display_name))
            released_orders = production.x_mes_order_ids.filtered(
                lambda order: order.state == 'released')
            if released_orders:
                released_orders.with_context(mes_force_cancel=True).action_cancel()
            # keep whatever actually happened, void the rest (no backorder)
            for move in production.move_raw_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel')):
                if move.quantity:
                    move.picked = True
            for move in production.move_finished_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel')):
                if move.quantity:
                    move.picked = True
            production.with_context(skip_backorder=True)._post_inventory(
                cancel_backorder=True)
            remaining_moves = (production.move_raw_ids | production.move_finished_ids).filtered(
                lambda move: move.state not in ('done', 'cancel'))
            if remaining_moves:
                remaining_moves.write({
                    'state': 'done',
                    'product_uom_qty': 0.0,
                })
            production.write({
                'date_finished': fields.Datetime.now(),
                'priority': '0',
                'is_locked': True,
                'state': 'done',
            })
        return True

    def action_confirm(self):
        draft_productions = self.filtered(lambda production: production.state == 'draft')
        draft_productions._apply_workshop_manufacturing_locations()
        draft_productions._check_workshop_manufacturing_locations()
        return super().action_confirm()

    def _compute_internal_serial_stats(self):
        for production in self:
            serials = self.env['sn.wsd.internal.serial'].search([
                '|', ('production_id', '=', production.id),
                ('current_production_id', '=', production.id),
            ])
            production.x_internal_serial_count = len(serials)
            production.x_internal_serial_passed = len(serials.filtered(lambda s: s.final_result == 'pass'))
            production.x_internal_serial_failed = len(serials.filtered(lambda s: s.final_result == 'fail'))
            production.x_internal_serial_scrapped = len(serials.filtered(lambda s: s.final_result == 'scrap'))
            production.x_meter_aging_batch_count = len(production.x_meter_aging_batch_ids)
            production.x_meter_pack_record_count = len(production.x_meter_pack_record_ids)

    def _update_meter_flow_state(self):
        state_priority = {
            'draft': 0,
            'material_ready': 1,
            'pcba_done': 2,
            'assembly_done': 3,
            'burned': 4,
            'initial_calibrated': 5,
            'aging': 6,
            'aging_done': 7,
            'verified': 8,
            'sealed': 9,
            'packed': 10,
            'done': 11,
        }
        operation_states = {
            'smt': 'pcba_done',
            'dip': 'pcba_done',
            'reflow': 'pcba_done',
            'aoi': 'pcba_done',
            'ict': 'pcba_done',
            'fct': 'pcba_done',
            'pcb_assembly': 'pcba_done',
            'assembly': 'assembly_done',
            'firmware': 'burned',
            'parameter_write': 'burned',
            'initial_calibration': 'initial_calibrated',
            'aging_load': 'aging',
            'aging_unload': 'aging_done',
            'verification': 'verified',
            'sealing': 'sealed',
            'packing': 'packed',
        }
        for production in self:
            target_state = production.x_meter_flow_state or 'draft'
            if production.state == 'done':
                target_state = 'done'
            else:
                serials = production._get_active_stage_serials()
                observed_states = []
                if serials.filtered('pack_date'):
                    observed_states.append('packed')
                if serials.filtered('seal_no'):
                    observed_states.append('sealed')
                if serials.filtered(lambda serial: serial.final_verification_result == 'pass'):
                    observed_states.append('verified')
                if serials.filtered(lambda serial: serial.aging_result == 'pass'):
                    observed_states.append('aging_done')
                completed_operations = production.x_mes_order_ids.x_route_operation_ids.filtered(
                    lambda operation: operation.x_ok_qty > 0 or operation.x_reported_ok_qty > 0
                )
                observed_states.extend(
                    operation_states[operation.operation_id.x_station_type]
                    for operation in completed_operations
                    if operation.operation_id.x_station_type in operation_states
                )
                if observed_states:
                    target_state = max(
                        [target_state, *observed_states],
                        key=lambda state: state_priority.get(state, 0),
                    )
            if production.x_meter_flow_state != target_state:
                production.x_meter_flow_state = target_state
        return True

    def _check_sn_uniqueness(self):
        self.ensure_one()
        if self.x_has_meter_operations and self.x_internal_serial_ids.filtered('pack_date'):
            return True
        return super()._check_sn_uniqueness()

    def _get_meter_packed_serials(self):
        self.ensure_one()
        return self.x_internal_serial_ids.filtered('pack_date')

    def _should_use_meter_mes_done_flow(self):
        self.ensure_one()
        return bool(self.x_has_meter_operations and self.product_tracking != 'lot' and self._get_meter_packed_serials())

    def _meter_mes_mark_done(self):
        for production in self:
            packed_serials = production._get_meter_packed_serials()
            if not packed_serials:
                continue
            done_qty = production.product_uom_id.round(min(len(packed_serials), production.product_qty))
            production.write({
                'qty_producing': done_qty,
                'qty_produced': done_qty,
            })

            moves_to_do = production.move_raw_ids.filtered(lambda move: move.state not in ('done', 'cancel') and move.picked)
            moves_to_cancel = production.move_raw_ids.filtered(lambda move: move.state not in ('done', 'cancel') and not move.picked)
            if moves_to_do:
                moves_to_do.with_context(skip_mo_check=True)._action_done(cancel_backorder=True)
            if moves_to_cancel:
                moves_to_cancel.with_context(skip_mo_check=True)._action_cancel()

            finished_moves = production.move_finished_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
            main_finished_moves = finished_moves.filtered(lambda move: move.product_id == production.product_id)
            extra_vals = production._prepare_finished_extra_vals()
            for move in main_finished_moves:
                move._set_quantity_done(done_qty)
                move.picked = bool(done_qty)
                if extra_vals and move.move_line_ids:
                    move.move_line_ids.write(extra_vals)
            byproduct_moves = finished_moves - main_finished_moves
            byproduct_moves.filtered(lambda move: not move.picked).picked = True

            production.x_meter_pack_record_ids.action_sync_stock_package()

            done_finished_moves = finished_moves.filtered(lambda move: move.picked)
            if done_finished_moves:
                done_finished_moves = done_finished_moves._action_done(cancel_backorder=True)
            else:
                done_finished_moves = self.env['stock.move']

            consume_move_lines = production.move_raw_ids.filtered(lambda move: move.state == 'done').mapped('move_line_ids')
            production.move_finished_ids.move_line_ids.consume_line_ids = [fields.Command.set(consume_move_lines.ids)]

            remaining_moves = (production.move_raw_ids | production.move_finished_ids).filtered(
                lambda move: move.state not in ('done', 'cancel')
            )
            if remaining_moves:
                remaining_moves.write({
                    'state': 'done',
                    'product_uom_qty': 0.0,
                })

            production.write({
                'date_finished': fields.Datetime.now(),
                'priority': '0',
                'is_locked': True,
                'state': 'done',
            })
            done_finished_moves._trigger_assign()
        return True

    def action_meter_recover_done_state(self):
        for production in self:
            if not production._should_use_meter_mes_done_flow():
                continue
            main_finished_moves = production.move_finished_ids.filtered(lambda move: move.product_id == production.product_id)
            cancelled_finished_moves = main_finished_moves.filtered(lambda move: move.state == 'cancel')
            active_finished_moves = main_finished_moves.filtered(lambda move: move.state not in ('done', 'cancel'))
            if cancelled_finished_moves and not active_finished_moves:
                template_move = cancelled_finished_moves[0]
                new_move_vals = template_move.copy_data({
                    'state': 'confirmed',
                    'picked': False,
                    'quantity': 0.0,
                    'lot_ids': [fields.Command.clear()],
                    'move_line_ids': [fields.Command.clear()],
                })[0]
                self.env['stock.move'].create(new_move_vals)
            if production.state == 'cancel':
                production.write({
                    'state': 'progress',
                    'is_locked': False,
                })
            production._meter_mes_mark_done()
        return True

    def button_mark_done(self):
        meter_productions = self.filtered(lambda production: production._should_use_meter_mes_done_flow())
        other_productions = self - meter_productions
        if meter_productions:
            res = meter_productions.pre_button_mark_done()
            if res is not True:
                return res
            meter_productions._meter_mes_mark_done()
        if other_productions:
            return super(MrpProduction, other_productions).button_mark_done()
        return True

    def _sn_recover_cancelled_finished_moves(self):
        for production in self:
            main_finished_moves = production.move_finished_ids.filtered(
                lambda move: move.product_id == production.product_id
            )
            cancelled_finished_moves = main_finished_moves.filtered(lambda move: move.state == 'cancel')
            active_finished_moves = main_finished_moves.filtered(lambda move: move.state not in ('done', 'cancel'))
            if cancelled_finished_moves and not active_finished_moves:
                template_move = cancelled_finished_moves[0]
                new_move_vals = template_move.copy_data({
                    'state': 'confirmed',
                    'picked': False,
                    'quantity': 0.0,
                    'lot_ids': [fields.Command.clear()],
                    'move_line_ids': [fields.Command.clear()],
                })[0]
                self.env['stock.move'].create(new_move_vals)
            if production.state == 'cancel':
                production.write({
                    'state': 'progress',
                    'is_locked': False,
                })
        return True

    def _sn_post_finished_shortfall(self):
        for production in self:
            shortfall_qty = production.product_qty - production.qty_produced
            if production.product_uom_id.compare(shortfall_qty, 0.0) <= 0:
                continue
            production._sn_recover_cancelled_finished_moves()
            production.write({
                'state': 'progress',
                'is_locked': False,
                'qty_producing': production.product_qty,
            })
            production.set_qty_producing()
            for move in production.move_finished_ids.filtered(
                lambda stock_move: stock_move.product_id == production.product_id
                and stock_move.state not in ('done', 'cancel')
            ):
                if move.has_tracking != 'none' and production.lot_producing_ids:
                    move.lot_ids = [fields.Command.set(production.lot_producing_ids.ids)]
                move._set_quantity_done(shortfall_qty)
                if move.has_tracking != 'none' and production.lot_producing_ids:
                    move.move_line_ids.filtered(lambda line: not line.picked).unlink()
                    if not move.move_line_ids.filtered(lambda line: line.quantity > 0 and line.picked):
                        lot_ids = production.lot_producing_ids
                        if move.has_tracking == 'serial':
                            line_commands = [
                                fields.Command.create({
                                    'product_id': move.product_id.id,
                                    'product_uom_id': move.product_uom.id,
                                    'quantity': 1.0,
                                    'picked': True,
                                    'lot_id': lot.id,
                                    'location_id': move.location_id.id,
                                    'location_dest_id': move.location_dest_id.id,
                                })
                                for lot in lot_ids[:int(shortfall_qty)]
                            ]
                        else:
                            line_commands = [fields.Command.create({
                                'product_id': move.product_id.id,
                                'product_uom_id': move.product_uom.id,
                                'quantity': shortfall_qty,
                                'picked': True,
                                'lot_id': lot_ids[0].id,
                                'location_id': move.location_id.id,
                                'location_dest_id': move.location_dest_id.id,
                            })]
                        move.move_line_ids = line_commands
                move.picked = True
            shortfall_moves = production.move_finished_ids.filtered(
                lambda move: move.product_id == production.product_id
                and move.state not in ('done', 'cancel')
                and move.quantity > 0
                and move.picked
            )
            shortfall_moves.with_context(skip_mo_check=True)._action_done(cancel_backorder=True)
            remaining_moves = production.move_finished_ids.filtered(
                lambda move: move.state not in ('done', 'cancel')
            )
            if remaining_moves:
                remaining_moves.write({
                    'state': 'done',
                    'product_uom_qty': 0.0,
                })
            production.write({
                'date_finished': fields.Datetime.now(),
                'priority': '0',
                'is_locked': True,
                'state': 'done',
            })
            production.move_finished_ids.filtered(lambda move: move.state == 'done')._trigger_assign()
        return True

    def action_api_sync_workorders(self):
        for production in self.filtered(lambda record: record.state not in ('done', 'cancel') and record.bom_id):
            production._link_bom(production.bom_id)
            production.action_confirm()
        return True

    def action_api_mark_done(self):
        shortfall_done_productions = self.filtered(
            lambda production: production.state == 'done'
            and production.product_uom_id.compare(production.product_qty - production.qty_produced, 0.0) > 0
        )
        if shortfall_done_productions:
            shortfall_done_productions._sn_post_finished_shortfall()
        productions_to_mark_done = self - shortfall_done_productions
        if not productions_to_mark_done:
            return True
        for production in productions_to_mark_done:
            if production.state in ('done', 'cancel'):
                production._sn_recover_cancelled_finished_moves()
            if not production.qty_producing:
                production.qty_producing = production.product_qty - production.qty_produced
            production.set_qty_producing()
            for move in production.move_raw_ids.filtered(lambda stock_move: stock_move.state not in ('done', 'cancel')):
                if move.quantity:
                    move.picked = True
            for move in production.move_finished_ids.filtered(lambda stock_move: stock_move.state not in ('done', 'cancel')):
                if move.product_id == production.product_id:
                    if move.has_tracking == 'lot' and production.lot_producing_ids:
                        move.lot_ids = [fields.Command.set(production.lot_producing_ids.ids)]
                    if move.has_tracking != 'serial' and not move.quantity:
                        move._set_quantity_done(production.qty_producing)
                if move.quantity:
                    move.picked = True
        result = super(MrpProduction, productions_to_mark_done.with_context(skip_backorder=True)).button_mark_done()
        productions_to_mark_done._sn_recover_cancelled_finished_moves()
        for production in productions_to_mark_done.filtered(lambda record: record.state not in ('done', 'cancel')):
            production.with_context(skip_backorder=True)._post_inventory(cancel_backorder=True)
            remaining_moves = (production.move_raw_ids | production.move_finished_ids).filtered(
                lambda move: move.state not in ('done', 'cancel')
            )
            if remaining_moves:
                remaining_moves.write({
                    'state': 'done',
                    'product_uom_qty': 0.0,
                })
            production.write({
                'date_finished': fields.Datetime.now(),
                'priority': '0',
                'is_locked': True,
                'state': 'done',
            })
            production.move_finished_ids.filtered(lambda move: move.state == 'done')._trigger_assign()
        return result if result is not None else True

    def action_generate_internal_serial_archives(self):
        orders = self.mapped('x_mes_order_ids').filtered(
            lambda order: order.state != 'cancelled'
        )
        if not orders:
            raise ValidationError(_('An MES order is required to generate internal serials.'))
        for order in orders:
            order.action_generate_missing_internal_serials()
        return True

    def action_open_internal_serials(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Internal Serials',
            'res_model': 'sn.wsd.internal.serial',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id, 'default_product_id': self.product_id.id},
        }

    def action_open_aging_batches(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Aging Batches',
            'res_model': 'sn.wsd.meter.aging.batch',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id},
        }

    def action_open_pack_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pack Records',
            'res_model': 'sn.wsd.meter.pack.record',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id},
        }
