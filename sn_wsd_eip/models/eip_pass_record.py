"""EIP collection staging: one row per completed station pass.

The row is born in the same transaction as the pass verdict backfill
(sn.wsd.serial.operation.history write hook) and carries the EIP common
fields verbatim. Value columns are filled by three extraction buckets:

* bucket 1 -- test detail items by project name (value mapping,
  filled at the test-result backfill phase, batch 2);
* bucket 2 -- device zone packets (reflow/wave), nearest packet before
  the pass, zone-name mapping, max per field / min for cooling;
* bucket 3 -- aging-room temperature points inside the pass enter/leave
  window (built-in logic, one line per point).

State machine: pending (default) -> delivered (taken by the collection
system, frozen afterwards). The pull endpoint is a separate project.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

AGING_INFO_CODE = '1011'

# EIP info code -> zone-packet model (bucket 2)
ZONE_PACKET_MODELS = {
    '1009': 'sn.wsd.device.reflow.record',
    '1010': 'sn.wsd.device.wave.record',
}


class EipPassRecord(models.Model):
    _name = 'sn.wsd.eip.pass.record'
    _description = 'EIP Station Pass Collection Record'
    _order = 'check_time desc, id desc'
    _rec_name = 'test_code'
    _check_company_auto = True

    # ----- anchors (snapshot columns keep the row self-contained) -----
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        index=True)
    history_id = fields.Many2one(
        'sn.wsd.serial.operation.history', string='Pass History',
        ondelete='set null', index=True,
        help='The station-pass ledger row this collection row was born '
             'from; unique anchor (clear-pass keeps the row, drops the '
             'anchor).')
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN', ondelete='set null',
        index=True)
    sn_name = fields.Char(string='SN (snapshot)', index=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', ondelete='set null',
        index=True, check_company=True)
    work_order_no = fields.Char(
        string='Work Order No', index=True,
        help='EIP WORK_ORDER_CODE: MES order name snapshot.')
    production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order',
        ondelete='set null', index=True, check_company=True)
    production_order_no = fields.Char(
        string='Production Order No', index=True,
        help='EIP PRODUCTION_ORDER_ID: manufacturing order name snapshot.')
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Route Operation',
        ondelete='set null', index=True, check_company=True)
    operation_id = fields.Many2one(
        'sn.wsd.operation', string='Operation', ondelete='set null',
        index=True, check_company=True)
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Work Center', ondelete='set null',
        index=True)
    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment', ondelete='set null',
        index=True,
        help='Report device (M_DEVICE_SN) when known, else the equipment '
             'maintained on the work center.')
    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result', string='Test Result',
        ondelete='set null', index=True,
        help='Device report this row was enriched from (report channel).')

    # ----- EIP common export columns -----
    info_type_code = fields.Char(
        string='Info Type Code', required=True, index=True,
        help='EIP INFO_TYPE_CODE, from the operation code mapping.')
    standard_version = fields.Integer(default=2, required=True)
    device_no = fields.Char(
        string='Device No', index=True,
        help='EIP DEVICE_NO: device chain -- report device code, else the '
             'work-center equipment code, else the work-center code.')
    test_code = fields.Char(
        string='Test Code', required=True, index=True,
        help='EIP TEST_CODE: unique per inspection '
             '("<info code>-<history id>").')
    model_code = fields.Char(
        string='Model Code',
        help='EIP MODEL_CODE: product specification, falling back to the '
             'drawing number.')
    pcb_code = fields.Char(
        string='PCB Code', index=True,
        help='EIP PCB_CODE: the SN itself (empty for 1011, the aging '
             'interface has no board identity).')
    test_name = fields.Char(
        string='Test Name', help='EIP TEST_NAME: the operation name.')
    check_time = fields.Datetime(
        string='Check Time', index=True,
        help='EIP CHECK_TIME: the pass leave time.')
    create_time = fields.Datetime(
        string='Create Time', default=fields.Datetime.now,
        help='EIP CREATE_TIME: when the row entered the MES.')
    upload_time = fields.Datetime(
        string='Upload Time',
        help='EIP UPLOAD_TIME: stamped when the collection system takes '
             'the row (pull endpoint, separate project).')
    conclusion = fields.Integer(
        string='Conclusion', index=True,
        help='EIP CONCLUSION: 0 pass, 1 fail.')

    # ----- value columns (three extraction buckets) -----
    current_value = fields.Float(string='Battery Current (uA)', digits=(10, 3))
    warming_zone = fields.Float(string='Warming Zone (C)', digits=(10, 1))
    constant_temperature_zone = fields.Float(
        string='Constant Temperature Zone (C)', digits=(10, 1))
    welding_zone = fields.Float(string='Welding Zone (C)', digits=(10, 1))
    cooling_zone = fields.Float(string='Cooling Zone (C)', digits=(10, 1))
    preheating_area = fields.Float(
        string='Preheating Area (C)', digits=(10, 1))
    agingroom_temperature = fields.Float(
        string='Aging Room Temperature (C)', digits=(10, 1),
        help='Window average for a quick glance; the pull endpoint ships '
             'one data row per point from the aging lines.')
    standard_value = fields.Float(
        string='Standard Value (C)', digits=(10, 1),
        help='Source pending decision; left empty for now.')
    check_duration = fields.Char(string='Check Duration (s)')
    testing_voltage = fields.Char(string='Testing Voltage (V)')
    leakage_current = fields.Float(
        string='Leakage Current (mA)', digits=(10, 3))
    average_error_type = fields.Char(string='Average Error Type')
    average_error = fields.Float(string='Average Error', digits=(10, 3))
    allowable_error = fields.Char(string='Allowable Error')
    real_error = fields.Float(string='Real Error', digits=(10, 3))
    software_version = fields.Char(string='Software Version')
    plant_code = fields.Char(string='Plant Code')
    nameplate_code = fields.Char(string='Nameplate Code')
    table_no = fields.Char(string='Table No')
    table_address = fields.Char(string='Table Address')
    asset_management_no = fields.Char(string='Asset Management No')

    # ----- state / metadata -----
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('delivered', 'Delivered'),
        ],
        required=True, default='pending', index=True,
        help='Pending: waiting for the collection system to pull it. '
             'Delivered: taken by the collection system, frozen -- no '
             'value extraction runs on a delivered row.')
    values_extracted = fields.Boolean(
        default=False,
        help='Set once a configured extraction pass ran on this row.')
    note = fields.Char(string='Note')

    line_ids = fields.One2many(
        'sn.wsd.eip.pass.record.line', 'record_id', string='Lines')

    _history_uniq = models.Constraint(
        'unique(company_id, history_id)',
        'This station-pass row is already collected.',
    )

    # ------------------------------------------------------------------
    # capture (phase 1 -- same transaction as the verdict backfill)
    # ------------------------------------------------------------------
    def _capture_from_history(self, history_rows):
        """Create one collection row per completed pass on a mapped
        operation, then run the in-DB extraction buckets (zone packets,
        aging points)."""
        Mapping = self.env['sn.wsd.eip.operation.mapping']
        records = self
        for history in history_rows:
            operation = history.route_operation_id.operation_id
            if not operation:
                continue
            mapping = Mapping.search([
                ('operation_id', '=', operation.id),
                ('company_id', 'in', [history.company_id.id, False]),
            ], limit=1)
            if not mapping:
                continue
            if self.search_count([
                    ('history_id', '=', history.id),
                    ('company_id', '=', history.company_id.id)]):
                continue
            order = history.mes_order_id
            production = order.production_id
            product = order.product_id
            workcenter = history.workcenter_id
            # device chain level 2: the equipment assigned to the work
            # center (sn.wsd.workcenter.equipment, first by sequence)
            equipment = (
                workcenter.sn_equipment_ids.sorted('sequence')[:1]
                .equipment_id)
            records |= self.create({
                'company_id': history.company_id.id,
                'history_id': history.id,
                'serial_identity_id': history.serial_identity_id.id,
                'sn_name': history.serial_identity_id.name,
                'mes_order_id': order.id,
                'work_order_no': order.name,
                'production_id': production.id,
                'production_order_no': production.name,
                'route_operation_id': history.route_operation_id.id,
                'operation_id': operation.id,
                'workcenter_id': workcenter.id,
                'equipment_id': equipment.id,
                'info_type_code': mapping.info_code,
                'device_no': equipment.code or workcenter.code,
                'test_code': f'{mapping.info_code}-{history.id}',
                'model_code': (
                    product.material_specification or product.default_code),
                'pcb_code': (
                    history.serial_identity_id.name
                    if mapping.info_code != AGING_INFO_CODE else False),
                'test_name': operation.name,
                'check_time': history.out_date,
                'conclusion': 1 if history.result == 'ng' else 0,
            })
        # single writer for every trigger: the extraction guards
        # (state / bucket / fill-empty) live inside, callers cannot
        # bypass them
        records._apply_value_extraction()

    # ------------------------------------------------------------------
    # extraction (single entry point for capture / backfill / cron)
    # ------------------------------------------------------------------
    def _apply_value_extraction(self):
        """Run every extraction bucket on ``self``. Each bucket is
        individually tolerant: an error is logged, never raised --
        collection must not disturb the pass flow. Batch 2 adds the
        test-detail bucket here."""
        try:
            self._extract_device_zones()
        except Exception as exc:  # noqa: BLE001 -- deliberate tolerance
            _logger.warning('EIP zone extraction failed: %s', exc)
        try:
            self._extract_aging_points()
        except Exception as exc:  # noqa: BLE001 -- deliberate tolerance
            _logger.warning('EIP aging extraction failed: %s', exc)

    def _extract_device_zones(self):
        """Bucket 2: for reflow (1009) / wave (1010) rows, take the
        nearest zone packet of the pass device at or before the check
        time, match zones by mapped name, aggregate max per field
        (cooling zone: min). Recompute-and-overwrite: a later, nearer
        packet supersedes the value taken at capture time."""
        Mapping = self.env['sn.wsd.eip.value.mapping']
        for record in self:
            packet_model = ZONE_PACKET_MODELS.get(record.info_type_code)
            if not packet_model or record.state == 'delivered':
                continue
            mappings = Mapping.search([
                ('info_type_code', '=', record.info_type_code),
                ('source_kind', '=', 'device_zone'),
                ('company_id', 'in', [record.company_id.id, False]),
            ])
            if not mappings or not record.device_no or not record.check_time:
                continue
            packet = self.env[packet_model].search([
                ('device_sn', '=', record.device_no),
                ('collect_time', '<=', record.check_time),
            ], order='collect_time desc, id desc', limit=1)
            if not packet:
                continue
            zones = {
                zone.zone_name: zone.temperature
                for zone in packet.zone_line_ids}
            values = {}
            for mapping in mappings:
                temperature = zones.get(mapping.source_key)
                if temperature is None:
                    continue
                current = values.get(mapping.eip_field)
                if current is None:
                    values[mapping.eip_field] = temperature
                elif mapping.eip_field == 'cooling_zone':
                    values[mapping.eip_field] = min(current, temperature)
                else:
                    values[mapping.eip_field] = max(current, temperature)
            if values:
                record.write(values)
                record.values_extracted = True

    def _extract_aging_points(self):
        """Bucket 3 (built-in): for aging rows, rebuild the aging lines
        from every temperature point of the pass device inside the
        enter..leave window and refresh the window average. Rebuild is
        idempotent (the window never changes)."""
        Aging = self.env['sn.wsd.device.aging.record']
        Line = self.env['sn.wsd.eip.pass.record.line']
        for record in self:
            if record.info_type_code != AGING_INFO_CODE:
                continue
            if record.state == 'delivered':
                continue
            history = record.history_id
            if not history or not history.in_date or not history.out_date:
                continue
            if not record.device_no:
                continue
            points = Aging.search([
                ('device_sn', '=', record.device_no),
                ('collect_time', '>=', history.in_date),
                ('collect_time', '<=', history.out_date),
            ], order='collect_time asc, id asc')
            record.line_ids.filtered(
                lambda line: line.line_type == 'aging_point').unlink()
            if points:
                Line.create([{
                    'record_id': record.id,
                    'line_type': 'aging_point',
                    'point_time': point.collect_time,
                    'actual_value': f'{point.temperature:g}',
                } for point in points])
                record.agingroom_temperature = (
                    sum(points.mapped('temperature')) / len(points))
                record.values_extracted = True
            else:
                record.agingroom_temperature = 0.0

    def _fill_empty_values(self, values):
        """Fill-only-empty writer: existing values are never overwritten
        (bucket 1/2 semantics). Returns True when something was filled."""
        vals = {}
        for fname, value in values.items():
            if fname in self._fields and not self[fname]:
                vals[fname] = value
        if vals:
            self.write(vals)
        return bool(vals)


class EipPassRecordLine(models.Model):
    """Point/detail snapshot of a collection row.

    aging_point lines: one per aging temperature point inside the pass
    window (point_time + actual_value; the pull endpoint ships one data
    row per point, at least 6 per order per spec).

    test_detail lines (batch 2): snapshot of the device test detail
    items the value extraction ran over, kept for audit.
    """
    _name = 'sn.wsd.eip.pass.record.line'
    _description = 'EIP Collection Record Line'
    _order = 'record_id, sequence, id'
    _check_company_auto = True

    record_id = fields.Many2one(
        'sn.wsd.eip.pass.record', required=True, ondelete='cascade',
        index=True)
    company_id = fields.Many2one(
        'res.company', related='record_id.company_id', store=True)
    line_type = fields.Selection(
        selection=[
            ('aging_point', 'Aging Point'),
            ('test_detail', 'Test Detail Item'),
        ],
        required=True, default='test_detail', index=True)
    sequence = fields.Integer(default=1)
    point_time = fields.Datetime(
        string='Point Time', help='Aging points only: collect time.')
    project_name = fields.Char(string='Project Name')
    lower_limit = fields.Char(string='Lower Limit')
    upper_limit = fields.Char(string='Upper Limit')
    actual_value = fields.Char(string='Actual Value')
    item_result = fields.Selection(
        selection=[('ok', 'OK'), ('ng', 'NG')], string='Item Result')
    raw_line = fields.Char(string='Raw Line')
