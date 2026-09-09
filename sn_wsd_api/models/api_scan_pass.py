from datetime import datetime, timezone

from odoo import _, api, models
from odoo.exceptions import AccessDenied, ValidationError

RESULT_PASS = 'ok'
RESULT_FAIL = 'ng'


class ApiBadRequest(ValidationError):
    """Device payload structural problem -> HTTP 400."""


class ApiUnauthorized(ValidationError):
    """Authentication failed -> HTTP 401."""


class ApiForbidden(ValidationError):
    """Authenticated but out of scope -> HTTP 403."""


class ApiNotFound(ValidationError):
    """Referenced record does not exist -> HTTP 404."""


class ApiUnprocessable(ValidationError):
    """Business-rule rejection -> HTTP 422."""

# AOI device contract (/api/v1/aoi/results): required top-level fields and
# the confirmedResult value that marks a real defect line
AOI_REQUIRED_FIELDS = (
    'productSn', 'machineName', 'retestResult', 'stationResult',
    'stationInfo', 'testTime', 'createTime', 'operator',
)
AOI_CONFIRMED_DEFECT = '确认不良'

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
    def _resolve_company(self, data_auth):
        """M_DATA_AUTH (organization code) -> company, matched on
        company_registry (the outward organization identifier)."""
        code = (data_auth or '').strip()
        if not code:
            raise ApiBadRequest(_('Organization is empty.'))
        company = self.env['res.company'].search(
            [('company_registry', '=', code)], limit=1)
        if not company:
            raise ApiNotFound(_('Organization %s does not exist.', code))
        return company

    def _match_defect_code(self, raw):
        """Dictionary lookup for a raw defect identifier (code first, then
        name), inside the current company."""
        raw = (raw or '').strip()
        DefectCode = self.env['sn.wsd.quality.defect.code']
        defect = DefectCode.search([
            ('code', '=ilike', raw),
            ('company_id', '=', self.env.company.id),
        ], limit=1) or DefectCode.search([
            ('name', '=ilike', raw),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not defect:
            raise ApiNotFound(_('Defect code %s does not exist.', raw))
        return defect

    def _pass_station_with_panel(self, identity, workcenter, result, defect,
                                 employee):
        """Station-pass the scanned SN, fanning out to its panel members on
        SMT orders (the scanned board carries the reported result, the
        others pass OK)."""
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
        return finished, mes_order, members

    @api.model
    def _parse_iso_datetime(self, value, field_name):
        """ISO 8601 device timestamp -> naive UTC datetime."""
        try:
            parsed = datetime.fromisoformat(str(value).strip())
        except (TypeError, ValueError):
            raise ApiBadRequest(
                _('Invalid %s: expected ISO 8601 datetime.', field_name))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    def _resolve_employee(self, code):
        code = (code or '').strip()
        if not code:
            raise ApiBadRequest(_('Employee code is required.'))
        employee = self.env['hr.employee'].search([
            '|', ('barcode', '=', code), ('user_id.login', '=', code),
        ], limit=1)
        if not employee:
            raise ApiNotFound(_('Employee %s does not exist in MES.', code))
        return employee

    def _resolve_workcenter(self, code):
        code = (code or '').strip()
        workcenter = self.env['mrp.workcenter'].search([('code', '=', code)], limit=1)
        if not workcenter:
            raise ApiNotFound(_('Work center %s does not exist.', code))
        return workcenter

    def _normalize_result(self, raw):
        raw = (raw or '').strip().lower()
        if raw == 'ok':
            return RESULT_PASS
        if raw == 'ng':
            return RESULT_FAIL
        raise ApiUnprocessable(_('The test result must be OK or NG.'))

    def _resolve_identity(self, sn_name, nameplate_first=True):
        """SN -> identity. A nameplate scanned as the SN resolves to its
        machine SN through the latest nameplate binding."""
        sn_name = (sn_name or '').strip()
        if not sn_name:
            raise ApiBadRequest(_('SN is required.'))
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
            raise ApiUnprocessable(_('SN %s is inactive.', sn_name))
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
        raise ApiUnprocessable(_(
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
        """Route one identity through the one-scan station kernel, shared
        with the terminal/PDA channels.

        A device report at X means X finished this board: an SN parked at
        another operation is pulled forward (that operation completes OK,
        the board enters X), then X's own result is written. An OK at a
        non-end operation auto-parks the board at the next station when the
        route is linear; a fork leaves it in transit for the branch
        station's own scan."""
        Wip = self.env['sn.wsd.serial.wip']
        operator_code = (
            employee.barcode
            or (employee.user_id.login if employee.user_id else False))
        wip = Wip.search([('serial_identity_id', '=', identity.id)], limit=1)
        if wip:
            mes_order = wip.mes_order_id
            route_op = wip.route_operation_id
            if route_op.operation_id != workcenter.x_operation_id:
                # arrival pull: the parked operation hands the board over
                mes_order.leave_station(identity, 'ok',
                                        operator_code=operator_code)
                target_op = mes_order.x_mes_route_id.operation_ids.filtered(
                    lambda r: r.operation_id == workcenter.x_operation_id)[:1]
                # 首件保持：到位已随出站登记，检验未判定时本站不接板——
                # 板停在途（不 raise，防止回滚到位登记）
                if mes_order.must_hold_for_fai(identity, target_op):
                    return False, mes_order
                mes_order.scan_enter(identity.name, workcenter)
                route_op = target_op
            finished = mes_order.leave_station(
                identity, result, ng_defect=defect,
                operator_code=operator_code)
            if result != RESULT_FAIL and not finished:
                self._park_at_successor(mes_order, route_op, identity)
            return finished, mes_order
        mes_order = self._find_live_order(workcenter)
        mes_order.scan_enter(identity.name, workcenter)
        route_op = mes_order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == workcenter.x_operation_id)[:1]
        finished = mes_order.leave_station(
            identity, result, ng_defect=defect,
            operator_code=operator_code)
        if result != RESULT_FAIL and not finished:
            self._park_at_successor(mes_order, route_op, identity)
        return finished, mes_order

    def _park_at_successor(self, mes_order, route_op, identity):
        """After an OK at a non-end operation, park the board at the next
        station when the route is linear; forks stay in transit (the branch
        station's own scan picks the board up)."""
        successor = mes_order._station_successors(route_op)[:1]
        if successor:
            mes_order.enter_station(
                identity, successor, workcenter=successor.workcenter_id)

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
        # M_DATA_AUTH scopes the whole call: identity registry, defect
        # dictionary, live order and station kernel all resolve in company.
        self = self.with_company(
            self._resolve_company(payload.get('M_DATA_AUTH')))
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
            defect = self._match_defect_code(payload.get('M_STR2') or 'TEST1')
        # panel fan-out: SMT orders resolve the whole panel from the scanned
        # board; the scanned board carries the reported result, the others
        # pass OK
        finished, mes_order, members = self._pass_station_with_panel(
            identity, workcenter, result, defect, employee)
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
        # M_TOOLING and device fields are record-only payloads (kept in the
        # request log); key-material usage counting happens in the station
        # kernel (leave_station) for every board that passes.
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
        self = self.with_company(
            self._resolve_company(payload.get('M_DATA_AUTH')))
        workcenter = self._resolve_workcenter(payload.get('M_WORK_STATIONSN'))
        mes_order = self._find_live_order(workcenter)
        identity = mes_order.generate_sn()
        return {'ok': True, 'sn': identity.name, 'mes_order': mes_order.name}

    # ------------------------------------------------------------------
    # AOI endpoint (/api/v1/aoi/results)
    # ------------------------------------------------------------------
    def _aoi_primary_defect(self, details):
        """NG primary defect: dictionary lookup of the defectCode of the
        first confirmed defect line."""
        for detail in details:
            if (detail.get('confirmedResult') or '').strip() == AOI_CONFIRMED_DEFECT:
                return self._match_defect_code(detail.get('defectCode'))
        raise ApiUnprocessable(
            _('NG result requires a confirmed defect detail.'))

    @api.model
    def submit_aoi_result(self, payload):
        """AOI device upload: one call = AOI test result + station pass
        through the same kernel as scan-pass. machineName carries the
        work-center code and the company comes from the work center (the
        device contract has no M_DATA_AUTH)."""
        payload = payload or {}
        for field_name in AOI_REQUIRED_FIELDS:
            if not str(payload.get(field_name) or '').strip():
                raise ApiBadRequest(f'Missing required field: {field_name}')
        details = [detail for detail in (payload.get('defectDetails') or [])
                   if isinstance(detail, dict)]
        for index, detail in enumerate(details):
            for field_name in ('defectCode', 'defectName', 'confirmedResult'):
                if not str(detail.get(field_name) or '').strip():
                    raise ApiBadRequest(
                        f'Missing required field: defectDetails[{index}].{field_name}')
        test_time = self._parse_iso_datetime(payload.get('testTime'), 'testTime')
        self._parse_iso_datetime(payload.get('createTime'), 'createTime')
        if (payload.get('retestTime') or '').strip():
            self._parse_iso_datetime(payload.get('retestTime'), 'retestTime')

        workcenter = self._resolve_workcenter(payload.get('machineName'))
        self = self.with_company(workcenter.company_id)
        employee = self._resolve_employee(payload.get('operator'))
        result = self._normalize_result(payload.get('stationResult'))
        identity = self._resolve_identity(payload.get('productSn'))
        if not identity:
            identity = self.env['sn.wsd.serial.identity'].get_or_create(
                (payload.get('productSn') or '').strip(), self.env.company,
                origin_type='external')
        defect = False
        if result == RESULT_FAIL:
            defect = self._aoi_primary_defect(details)

        # idempotency gate BEFORE the station pass: a resent upload must not
        # pass the station a second time
        external_event_id = (payload.get('logCode') or '').strip() or (
            f"aoi:{payload.get('machineName')}:{identity.name}:"
            f"{payload.get('testTime')}")
        existing = self.env['sn.wsd.mes.test.result'].search([
            ('external_event_id', '=', external_event_id),
            ('source_system', '=', 'AOI'),
        ], limit=1)
        if existing:
            return {'ok': True, 'test_result_id': existing.id}

        finished, mes_order, members = self._pass_station_with_panel(
            identity, workcenter, result, defect, employee)
        route_operation = self._route_operation(mes_order, workcenter)
        result_info = self.env['sn.wsd.mes.test.result'].ingest_meter_test_result(
            serial_number=identity.name,
            test_type='aoi',
            result=result,
            workcenter_code=workcenter.code,
            operator_code=payload.get('operator'),
            tester_channel=(payload.get('fileName') or '').strip() or None,
            note=(payload.get('stationInfo') or '').strip() or None,
            payload=payload,
            test_time=test_time,
            external_event_id=external_event_id,
            source_system='AOI',
            mes_order_id=mes_order.id,
            route_operation_id=route_operation.id,
        )
        test_result = self.env['sn.wsd.mes.test.result'].browse(
            result_info.get('test_result_id')).exists()
        if test_result and not result_info.get('duplicated'):
            if defect:
                test_result.defect_code_id = defect
            self.env['sn.wsd.aoi.defect.detail'].create([{
                'test_result_id': test_result.id,
                'sequence': index,
                'part_id': detail.get('partId'),
                'position': detail.get('position'),
                'defect_code': detail.get('defectCode'),
                'defect_name': detail.get('defectName'),
                'confirmed_result': detail.get('confirmedResult'),
                'image_path': detail.get('imagePath'),
                'payload': detail,
            } for index, detail in enumerate(details, start=1)])
        # SMT online-material deduction on the same kernel terms as scan-pass
        if mes_order._is_smt_route_order():
            consumption = self.env['sn.smt.material.consumption']
            for member in members:
                consumption.consume_for_serial(
                    route_operation, identity=member,
                    operator_code=payload.get('operator'),
                    external_event_id=external_event_id,
                    source_system='AOI',
                )
        return {'ok': True, 'test_result_id': result_info.get('test_result_id')}

    # ------------------------------------------------------------------
    # Laser endpoint (/api/v1/laser/print-requests)
    # ------------------------------------------------------------------
    LASER_MAX_QUANTITY = 10000

    @api.model
    def submit_laser_print_request(self, payload):
        """Laser printer batch SN reservation: workOrderNo -> the
        manufacturing order's product sequence (shared with the order-form
        button and next-sn, numbers never repeat). Optional panelQty
        auto-associates the printed SNs into panels in generation order (a
        trailing short panel is created as-is, no divisibility check)."""
        payload = payload or {}
        self = self.with_company(
            self._resolve_company(payload.get('M_DATA_AUTH')))
        work_order_no = (payload.get('workOrderNo') or '').strip()
        if not work_order_no:
            raise ApiBadRequest(_('Missing required field: workOrderNo'))
        production = self.env['mrp.production'].search([
            ('name', '=', work_order_no),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not production:
            raise ApiNotFound(_(
                'Manufacturing order %s does not exist.', work_order_no))
        raw_quantity = payload.get('quantity')
        if isinstance(raw_quantity, float) and not raw_quantity.is_integer():
            raw_quantity = None
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            quantity = 0
        if quantity < 1 or quantity > self.LASER_MAX_QUANTITY:
            raise ApiUnprocessable(_(
                'Quantity must be a positive integer no greater than %s.',
                self.LASER_MAX_QUANTITY))
        raw_panel_qty = payload.get('panelQty') or 0
        if isinstance(raw_panel_qty, float) and not raw_panel_qty.is_integer():
            raw_panel_qty = -1
        try:
            panel_qty = int(raw_panel_qty)
        except (TypeError, ValueError):
            panel_qty = -1
        if panel_qty < 0:
            raise ApiUnprocessable(_(
                'Panel quantity must be a positive integer.'))
        self._resolve_employee(payload.get('operator'))

        sequence = production._sn_product_sequence()
        serial_numbers = []
        for _index in range(quantity):
            serial_no = sequence.sudo().next_by_code(sequence.code)
            if not serial_no:
                raise ApiUnprocessable(_('No SN sequence is configured.'))
            self.env['sn.wsd.serial.identity'].create({
                'name': serial_no,
                'company_id': self.env.company.id,
                'origin_type': 'laser',
                'origin_production_id': production.id,
            })
            serial_numbers.append(serial_no)
        if panel_qty > 0:
            for start in range(0, quantity, panel_qty):
                chunk = serial_numbers[start:start + panel_qty]
                self.env['sn.smt.pcb.panel']._create_from_api({
                    'productNo': work_order_no,
                    'quantity': len(chunk),
                    'bindings': [
                        {'boardNo': index, 'proSn': serial_no}
                        for index, serial_no in enumerate(chunk, start=1)
                    ],
                }, production_id=production.id)
        return {
            'ok': True,
            'productSnList': serial_numbers,
            'quantity': quantity,
            'panelQty': panel_qty,
        }

    # ------------------------------------------------------------------
    # Device login endpoint (/api/v1/auth/check)
    # ------------------------------------------------------------------
    @api.model
    def auth_check(self, payload, credential=None):
        """Device operator login: real Odoo credentials (userName/password)
        + organization membership + employee precheck (the same employee
        rules as scan-pass, so a login that passes will pass stations).
        Without userName/password the call is a pure health probe. The
        controller hands the raw password in ``credential`` and passes a
        redacted payload copy, so the request log never stores it."""
        payload = payload or {}
        credential = credential or {}
        self = self.with_company(
            self._resolve_company(payload.get('M_DATA_AUTH')))
        user_name = (payload.get('userName') or '').strip()
        password = credential.get('password') or ''
        if not user_name and not password:
            # pure health probe
            return {}
        if not user_name:
            raise ApiBadRequest(_('Missing required field: userName'))
        if not password:
            raise ApiBadRequest(_('Missing required field: password'))
        try:
            self.env['res.users'].sudo().authenticate(
                {'type': 'password', 'login': user_name,
                 'password': password},
                {'interactive': False})
        except AccessDenied:
            raise ApiUnauthorized(_('Invalid account or password.'))
        user = self.env['res.users'].sudo().search(
            [('login', '=', user_name)], limit=1)
        company = self.env.company
        if not user or company.id not in user.company_ids.ids:
            raise ApiForbidden(_(
                'Account %s does not belong to this organization.',
                user_name))
        employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id),
            ('company_id', '=', company.id),
        ], limit=1)
        if not employee:
            raise ApiNotFound(
                _('Employee %s does not exist in MES.', user_name))
        return {
            'userName': user_name,
            'employeeName': employee.name,
        }

    # ------------------------------------------------------------------
    # Dictionary endpoints (frozen device contracts: /api/v1/... search)
    # ------------------------------------------------------------------
    @api.model
    def search_mes_orders(self, payload):
        """work_order (manufacturing-order keyword) -> flat list of the
        un-cancelled MES-order numbers below the matching productions."""
        payload = payload or {}
        self = self.with_company(
            self._resolve_company(payload.get('M_DATA_AUTH')))
        keyword = (payload.get('work_order') or '').strip()
        if not keyword:
            raise ApiBadRequest(_('Missing required field: work_order'))
        productions = self.env['mrp.production'].sudo().search([
            ('name', 'ilike', keyword),
            ('company_id', '=', self.env.company.id),
        ])
        if not productions:
            return []
        orders = self.env['sn.wsd.mes.order'].sudo().search([
            ('production_id', 'in', productions.ids),
            ('state', '!=', 'cancelled'),
        ], order='id desc')
        return orders.mapped('name')

    @api.model
    def search_work_centers(self, payload):
        """work_station keyword (empty = all) -> [[code, name]] pairs."""
        payload = payload or {}
        self = self.with_company(
            self._resolve_company(payload.get('M_DATA_AUTH')))
        keyword = (payload.get('work_station') or '').strip()
        domain = [('company_id', '=', self.env.company.id)]
        if keyword:
            domain = domain + [
                '|', ('code', 'ilike', keyword), ('name', 'ilike', keyword)]
        workcenters = self.env['mrp.workcenter'].sudo().search(
            domain, order='code asc, id asc')
        return [[wc.code or '', wc.name or ''] for wc in workcenters]

    @api.model
    def search_defect_codes(self, payload):
        """err_name keyword (empty = all) -> [[code, name]] pairs."""
        payload = payload or {}
        self = self.with_company(
            self._resolve_company(payload.get('M_DATA_AUTH')))
        keyword = (payload.get('err_name') or '').strip()
        domain = [('company_id', '=', self.env.company.id)]
        if keyword:
            domain = domain + [
                '|', ('code', 'ilike', keyword), ('name', 'ilike', keyword)]
        defects = self.env['sn.wsd.quality.defect.code'].sudo().search(
            domain, order='code asc, id asc')
        return [[d.code or '', d.name or ''] for d in defects]
