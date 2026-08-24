from odoo import _, api, models
from odoo.exceptions import ValidationError

RESULT_PASS = 'ok'
RESULT_FAIL = 'ng'

# old-API craft document fields -> document type codes (production.process.doc.type)
PROCESS_DOC_FIELDS = {
    'M_PARAMETER_PLAN': 'parameter_plan',
    'M_PROGRAM_NUM': 'program_version',
    'M_TEST_PLAN': 'test_plan',
    'M_SOFTWARE_NUM': 'production_software',
}

# old-API component fields -> component binding types
COMPONENT_FIELDS = {
    'M_MAIN_ID': 'main_pcb',
    'M_MODULE_ID': 'comm_module',
    'M_LEADSEAL_ID': 'leadseal',
}


class SnWsdApiService(models.AbstractModel):
    """Device-API orchestration: one fat scan-pass call reuses the same
    business services the shop-floor terminal runs on (identity registry,
    station kernel, test results, bindings, consumption)."""
    _name = 'sn.wsd.api.service'
    _description = 'SN WSD Device API Service'

    # ------------------------------------------------------------------
    # resolution helpers
    # ------------------------------------------------------------------
    def _resolve_employee(self, code):
        code = (code or '').strip()
        if not code:
            raise ValidationError(_('Employee code is required.'))
        employee = self.env['hr.employee'].search([
            '|', ('barcode', '=', code), ('user_id.login', '=', code),
        ], limit=1)
        if not employee:
            raise ValidationError(_('Employee %s does not exist in MES.', code))
        return employee

    def _resolve_workcenter(self, code):
        code = (code or '').strip()
        workcenter = self.env['mrp.workcenter'].search([('code', '=', code)], limit=1)
        if not workcenter:
            raise ValidationError(_('Work center %s does not exist.', code))
        return workcenter

    def _normalize_result(self, raw):
        raw = (raw or '').strip().lower()
        if raw == 'ok':
            return RESULT_PASS
        if raw == 'ng':
            return RESULT_FAIL
        raise ValidationError(_('The test result must be OK or NG.'))

    def _resolve_identity(self, sn_name, nameplate_first=True):
        """SN -> identity. A nameplate scanned as the SN resolves to its
        machine SN through the latest nameplate binding."""
        sn_name = (sn_name or '').strip()
        if not sn_name:
            raise ValidationError(_('SN is required.'))
        company = self.env.company
        if nameplate_first:
            binding = self.env['sn.wsd.serial.binding'].search([
                ('serial_identity_id.name', '=', sn_name),
                ('binding_type', '=', 'nameplate'),
                ('company_id', '=', company.id),
            ], order='binding_date desc, id desc', limit=1)
            if binding:
                return binding.bound_serial_identity_id
        identity = self.env['sn.wsd.serial.identity'].with_context(
            active_test=False).search([
                ('name', '=', sn_name), ('company_id', '=', company.id),
            ], limit=1)
        if identity and not identity.active:
            raise ValidationError(_('SN %s is inactive.', sn_name))
        return identity or self.env['sn.wsd.serial.identity']

    def _panel_members(self, identity, mes_order):
        """SMT orders only: identities of the panel boards of the scanned
        SN inside this MES order (the scanned board included)."""
        if not mes_order._is_smt_route_order():
            return identity
        board = self.env['sn.smt.pcb.board'].search([
            ('pro_sn', '=', identity.name),
            ('panel_id.production_id', '=', mes_order.production_id.id),
            ('panel_id.state', '!=', 'done'),
        ], limit=1)
        if not board:
            return identity
        # SNs are printed (laser) and panel-associated with the MES order
        # BEFORE station passing: all member identities already exist
        members = self.env['sn.wsd.serial.identity'].search([
            ('name', 'in', board.panel_id.board_ids.mapped('pro_sn')),
            ('company_id', '=', identity.company_id.id),
        ])
        return members or identity

    def _find_live_order(self, workcenter):
        """The live (online) MES order running through this work center."""
        operation = workcenter.x_operation_id
        orders = self.env['sn.wsd.mes.order'].search([
            ('state', 'not in', ('cancelled', 'done')),
            ('x_online_date', '!=', False),
            ('x_manage_mode', '=', 'station'),
        ]).filtered(lambda o: (
            not workcenter.x_production_line_id
            or o.production_line_id == workcenter.x_production_line_id))
        for order in orders:
            if order.x_mes_route_id.operation_ids.filtered(
                    lambda r: r.operation_id == operation):
                return order
        raise ValidationError(_(
            'No online MES order runs through work center %s.',
            workcenter.code or workcenter.name))

    def _route_operation(self, mes_order, workcenter):
        route_operation = mes_order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == workcenter.x_operation_id)
        if not route_operation:
            raise ValidationError(_(
                'Work center %s does not match any operation of MES order %s.',
                workcenter.code or workcenter.name, mes_order.name))
        return route_operation[:1]

    # ------------------------------------------------------------------
    # station kernel orchestration (one report = one station pass)
    # ------------------------------------------------------------------
    def _pass_station(self, identity, workcenter, result, defect, employee):
        """Route one identity through the station kernel, mirroring the
        terminal: WIP at this operation -> leave; parked elsewhere ->
        error; not in flow -> enter (feed) then leave."""
        Wip = self.env['sn.wsd.serial.wip']
        wip = Wip.search([('serial_identity_id', '=', identity.id)], limit=1)
        if wip:
            if wip.route_operation_id.operation_id != workcenter.x_operation_id:
                raise ValidationError(_(
                    'SN %(sn)s is in progress at operation %(op)s of order '
                    '%(order)s; use the matching station.',
                    sn=identity.name,
                    op=wip.route_operation_id.display_label,
                    order=wip.mes_order_id.name))
            mes_order = wip.mes_order_id
            return mes_order.leave_station(
                identity, result, ng_defect=defect), mes_order
        mes_order = self._find_live_order(workcenter)
        mes_order.scan_enter(identity.name, workcenter)
        return mes_order.leave_station(
            identity, result, ng_defect=defect), mes_order

    # ------------------------------------------------------------------
    # craft documents / components / nameplate / tooling / packing
    # ------------------------------------------------------------------
    def _check_process_documents(self, production, route_operation, payload):
        for field, type_code in PROCESS_DOC_FIELDS.items():
            value = (payload.get(field) or '').strip()
            if not value:
                continue
            doc = self.env['production.process.document'].search([
                ('production_id', '=', production.id),
                ('route_operation_code', '=', route_operation.operation_id.code or route_operation.operation_id.name),
                ('type_id.code', '=', type_code),
            ], limit=1)
            if not doc or value not in doc.code_ids.mapped('code'):
                raise ValidationError(_(
                    '%(field)s %(value)s is not maintained on operation '
                    '%(op)s of manufacturing order %(order)s.',
                    field=field, value=value,
                    op=route_operation.display_label,
                    order=production.display_name))

    def _register_components(self, identity, route_operation, payload, test_result):
        bindings = []
        for field, component_type in COMPONENT_FIELDS.items():
            raw = (payload.get(field) or '').strip()
            for sn in filter(None, [part.strip() for part in raw.split('|')]):
                bindings.append({
                    'component_type': component_type,
                    'component_sn': sn,
                })
        if bindings:
            self.env['sn.wsd.meter.component.binding'].register_component_bindings(
                identity, bindings,
                workorder=route_operation, test_result=test_result)

    def _bind_nameplate(self, machine_identity, nameplate_sn):
        nameplate_sn = (nameplate_sn or '').strip()
        if not nameplate_sn:
            return
        company = self.env.company
        nameplate = self.env['sn.wsd.serial.identity'].get_or_create(
            nameplate_sn, company, origin_type='external')
        existing = self.env['sn.wsd.serial.binding'].search([
            ('serial_identity_id', '=', nameplate.id),
            ('bound_serial_identity_id', '=', machine_identity.id),
            ('binding_type', '=', 'nameplate'),
        ], limit=1)
        if existing:
            # re-binding an earlier pair (physical swap back): promote its
            # historical row as current again instead of skipping silently
            if not existing.is_current:
                existing._promote_as_current()
            return
        # overwrite mode: a new row supersedes any previous binding of this
        # nameplate; the old rows stay as history
        self.env['sn.wsd.serial.binding'].create({
            'serial_identity_id': nameplate.id,
            'bound_serial_identity_id': machine_identity.id,
            'binding_type': 'nameplate',
            'source': 'api',
        })

    def _key_material_lines(self, mes_order, route_operation, workcenter):
        return self.env['sn.wsd.drawing.material'].search([
            ('x_drawing_no', '=', mes_order.production_id.product_id.default_code or False),
            ('workshop_id', '=', workcenter.x_workshop_id.id or False),
            ('operation_id', '=', route_operation.operation_id.id),
            ('x_side', '=', mes_order.x_side),
        ])

    def _register_tooling_usage(self, mes_order, route_operation, workcenter, payload, board_qty):
        """Key-material controlled tooling/consumables count on pass; any
        other uploaded tooling SN is recorded in the request log only."""
        raw = (payload.get('M_TOOLING') or '').strip()
        tooling_sns = [part.strip() for part in raw.split('|') if part.strip()]
        tooling_templates = self.env['sn.tooling.template']
        consumable_templates = self.env['sn.consumable.template']
        for line in self._key_material_lines(
                mes_order, route_operation, workcenter).line_ids:
            ref = line.material_ref
            if ref and ref._name == 'sn.tooling.template':
                tooling_templates |= ref
            elif ref and ref._name == 'sn.consumable.template':
                consumable_templates |= ref
        if not tooling_sns and not consumable_templates:
            return
        Tooling = self.env['sn.tooling']
        for sn in tooling_sns:
            tooling = Tooling.search([('sn', '=', sn)], limit=1)
            if not tooling or tooling.template_id not in tooling_templates:
                continue  # log-only
            if tooling.state == 'online':
                tooling.register_usage(board_qty)
        for template in consumable_templates:
            infos = self.env['sn.consumable.info'].search([
                ('template_id', '=', template.id), ('state', '=', 'loaded')])
            infos.register_usage(board_qty, mes_order=mes_order)

    def _handle_packing(self, identity, mes_order, route_operation, workcenter, payload, result):
        box = (payload.get('M_BOX_SN') or '').strip()
        pallet = (payload.get('M_SECOND_SN') or '').strip()
        if not box and not pallet:
            return False
        if result == RESULT_FAIL:
            raise ValidationError(_('The test result is NG.'))
        pack_model = self.env['sn.wsd.meter.pack.record']
        if pack_model.search_count([('serial_identity_id', '=', identity.id)]):
            raise ValidationError(
                _('SN %s already has a pack record.', identity.name))
        for code in filter(None, [box, pallet]):
            if pack_model.search_count([
                    ('carton_no', '=', code), ('active', '=', True)]) or \
                    pack_model.search_count([
                        ('pallet_no', '=', code), ('active', '=', True)]):
                raise ValidationError(
                    _('Container %s already exists in stock.', code))
        pack = pack_model.create({
            'serial_identity_id': identity.id,
            'production_id': mes_order.production_id.id,
            'pack_route_operation_id': route_operation.id,
            'carton_no': box or False,
            'pallet_no': pallet or False,
        })
        barcode_fields = [
            'M_PACK_LEFT_SEAL', 'M_PACK_LEFT_SEAL_RF', 'M_PACK_RIGHT_SEAL',
            'M_PACK_RIGHT_SEAL_RF', 'M_PACK_DOOR_SEAL', 'M_PACK_DOOR_SEAL_RF',
            'M_PACK_NAMEPLATE_RF', 'M_PACK_MODULE', 'M_PACK_MAC', 'M_PACK_TOP',
            'M_PACK_LEFT', 'M_PACK_RIGHT', 'M_PACK_BACK',
        ]
        lines = []
        for field in barcode_fields:
            value = (payload.get(field) or '').strip()
            if value:
                lines.append((0, 0, {'code': field, 'value': value}))
        if lines:
            pack.barcode_line_ids = lines
        return True

    # ------------------------------------------------------------------
    # entry points
    # ------------------------------------------------------------------
    @api.model
    def scan_pass(self, payload):
        employee = self._resolve_employee(payload.get('M_EMP'))
        workcenter = self._resolve_workcenter(payload.get('M_WORK_STATIONSN'))
        result = self._normalize_result(payload.get('M_TEST_RESULT'))
        identity = self._resolve_identity(payload.get('M_SN'))
        if not identity:
            identity = self.env['sn.wsd.serial.identity'].get_or_create(
                (payload.get('M_SN') or '').strip(), self.env.company,
                origin_type='external')
        defect = False
        if result == RESULT_FAIL:
            raw_defect = (payload.get('M_STR2') or 'TEST1').strip()
            defect = self.env['sn.wsd.quality.defect.code'].search([
                ('code', '=ilike', raw_defect),
                ('company_id', '=', self.env.company.id),
            ], limit=1) or self.env['sn.wsd.quality.defect.code'].search([
                ('name', '=ilike', raw_defect),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
            if not defect:
                raise ValidationError(
                    _('Defect code %s does not exist.', raw_defect))
        # panel fan-out: SMT orders resolve the whole panel from the scanned
        # board; the scanned board carries the reported result, the others
        # pass OK
        probe_wip = self.env['sn.wsd.serial.wip'].search(
            [('serial_identity_id', '=', identity.id)], limit=1)
        probe_order = probe_wip.mes_order_id or self._find_live_order(workcenter)
        members = self._panel_members(identity, probe_order)
        # station pass for every member (first member = the scanned board)
        finished = False
        mes_order = probe_order
        for member in (identity | (members - identity)):
            member_result = result if member == identity else RESULT_PASS
            member_defect = defect if member == identity else False
            finished, mes_order = self._pass_station(
                member, workcenter, member_result, member_defect, employee)
        route_operation = self._route_operation(mes_order, workcenter)
        # test result for the scanned board only (station pass already
        # cleared the WIP row, so the order context is passed explicitly)
        result_info = self.env['sn.wsd.mes.test.result'].ingest_meter_test_result(
            serial_number=identity.name,
            result=result,
            workcenter_code=workcenter.code,
            operator_code=payload.get('M_EMP'),
            payload=payload,
            mes_order_id=mes_order.id,
            route_operation_id=route_operation.id,
        )
        test_result = self.env['sn.wsd.mes.test.result'].browse(
            result_info['test_result_id']).exists()
        production = mes_order.production_id
        self._check_process_documents(production, route_operation, payload)
        self._register_components(identity, route_operation, payload, test_result)
        self._bind_nameplate(identity, payload.get('M_STR1'))
        self._register_tooling_usage(
            mes_order, route_operation, workcenter, payload, len(members))
        # SMT online material deduction, one board at a time (idempotent
        # per SN+order)
        if mes_order._is_smt_route_order():
            consumption = self.env['sn.smt.material.consumption']
            for member in members:
                consumption.consume_for_serial(
                    route_operation, identity=member,
                    operator_code=payload.get('M_EMP'),
                    external_event_id=payload.get('external_event_id'),
                    source_system=payload.get('source_system'),
                )
        self._handle_packing(
            identity, mes_order, route_operation, workcenter, payload, result)
        return {
            'ok': True,
            'sn': identity.name,
            'panel_qty': len(members),
            'finished': finished,
            'test_result_id': result_info.get('test_result_id'),
        }

    @api.model
    def request_next_sn(self, payload):
        """B2: a device (e.g. the laser printer) asks for the next SN of the
        live order on its line; the SN identity is created and reserved."""
        workcenter = self._resolve_workcenter(payload.get('M_WORK_STATIONSN'))
        mes_order = self._find_live_order(workcenter)
        identity = mes_order.generate_sn()
        return {'ok': True, 'sn': identity.name, 'mes_order': mes_order.name}
