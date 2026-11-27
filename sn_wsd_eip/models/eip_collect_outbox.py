"""EIP collect outbox: delivery snapshots of cleansed collection rows.

One row = one record of the gateway ``data`` array. The cleansing
engine materialises payloads here (JSON shaped per the interface spec,
field names/precisions/date formats already applied); the endpoint only
claims FIFO and marks delivered. Re-cleansing of an undelivered row
supersedes its old snapshots; nothing is ever deleted.
"""
from odoo import api, fields, models


# ---- payload display columns ----
# every spec field as a readable column: the payload is synthesized
# once at cleansing and these non-stored columns read the keys
# back out, so the outbox can be reviewed like a plain table
PAYLOAD_COLUMN_MAP = {
    'payload_standard_version': 'STANDARD_VERSION',
    'payload_production_order_id': 'PRODUCTION_ORDER_ID',
    'payload_work_order_code': 'WORK_ORDER_CODE',
    'payload_info_type_code': 'INFO_TYPE_CODE',
    'payload_device_no': 'DEVICE_NO',
    'payload_test_code': 'TEST_CODE',
    'payload_model_code': 'MODEL_CODE',
    'payload_pcb_code': 'PCB_CODE',
    'payload_check_time': 'CHECK_TIME',
    'payload_create_time': 'CREATE_TIME',
    'payload_upload_time': 'UPLOAD_TIME',
    'payload_conclusion': 'CONCLUSION',
    'payload_test_name': 'TEST_NAME',
    'payload_current_value': 'CURRENT_VALUE',
    'payload_warming_zone': 'WARMING_ZONE',
    'payload_constant_temperature_zone': 'CONSTANT_TEMPERATURE_ZONE',
    'payload_welding_zone': 'WELDING_ZONE',
    'payload_cooling_zone': 'COOLING_ZONE',
    'payload_preheating_area': 'PREHEATING_AREA',
    'payload_agingroom_temperature': 'AGINGROOM_TEMPERATURE',
    'payload_standard_value': 'STANDARD_VALUE',
    'payload_check_duration': 'CHECK_DURATION',
    'payload_testing_voltage': 'TESTING_VOLTAGE',
    'payload_leakage_current': 'LEAKAGE_CURRENT',
    'payload_allowable_error': 'ALLOWABLE_ERROR',
    'payload_real_error': 'REAL_ERROR',
    'payload_average_error_type': 'AVERAGE_ERROR_TYPE',
    'payload_average_error': 'AVERAGE_ERROR',
    'payload_software_version': 'SOFTWARE_VERSION',
    'payload_plant_code': 'PLANT_CODE',
    'payload_nameplate_code': 'NAMEPLATE_CODE',
    'payload_table_no': 'TABLE_NO',
    'payload_table_address': 'TABLE_ADDRESS',
    'payload_asset_management_no': 'ASSET_MANAGEMENT_NO',
    'payload_measured_value': 'MEASURED_VALUE',
    'payload_error_value': 'ERROR_VALUE',
    'payload_logic_address': 'LOGIC_ADDRESS',
    'payload_bureau_num': 'BUREAU_NUM',
}


class EipCollectOutbox(models.Model):
    _name = 'sn.wsd.eip.collect.outbox'
    _description = 'EIP Collect Outbox'
    _order = 'id'
    _rec_name = 'test_code'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    source_id = fields.Many2one(
        'sn.wsd.eip.pass.record', string='Collection Row',
        ondelete='set null', index=True, check_company=True,
        help='Cleansed collection row this snapshot was built from; the '
             'snapshot columns stay self-contained if the row itself is '
             'ever removed.')
    info_type_code = fields.Char(
        string='Info Type Code', required=True, index=True)
    family = fields.Selection(
        selection=[
            ('meter', 'Electricity Meter'),
            ('collector', 'Collection Device'),
        ],
        string='Device Category', required=True, index=True)
    test_code = fields.Char(string='Test Code', index=True)
    payload = fields.Json(
        string='Payload',
        help='The exact data[] record shipped to the gateway: spec field '
             'names, types, precisions and date formats already applied.')
    state = fields.Selection(
        selection=[
            ('qualified', 'Qualified'),
            ('delivered', 'Delivered'),
        ],
        string='State', required=True, default='qualified', index=True,
        help='Qualified: waiting for the gateway to fetch it. Delivered: '
             'fetched, frozen forever. Re-cleansing of an undelivered row '
             'deletes its stale snapshots outright.')
    delivered_time = fields.Datetime(
        string='Delivered Time', readonly=True,
        help='When the gateway fetched this snapshot.')

    # ---- searchable keys (stored copies of payload keys) ----
    # the payload_* display columns are non-stored projections of the
    # JSON blob and cannot be searched in SQL; these three are what
    # users actually look snapshots up by, so they land in real columns
    work_order_no = fields.Char(
        string='Work Order No', compute='_compute_search_keys',
        store=True, index=True,
        help='WORK_ORDER_CODE of the payload: look snapshots up by work '
             'order.')
    production_order_no = fields.Char(
        string='Production Order No', compute='_compute_search_keys',
        store=True,
        help='PRODUCTION_ORDER_ID of the payload.')
    pcb_code = fields.Char(
        string='PCB Code', compute='_compute_search_keys',
        store=True, index=True,
        help='PCB_CODE of the payload (the SN); empty for aging rows '
             '(1011/2010), which fall back to the source SN.')

    @api.depends('payload', 'source_id.sn_name')
    def _compute_search_keys(self):
        for row in self:
            payload = row.payload or {}
            row.work_order_no = payload.get('WORK_ORDER_CODE') or ''
            row.production_order_no = payload.get('PRODUCTION_ORDER_ID') or ''
            row.pcb_code = (payload.get('PCB_CODE')
                            or (row.source_id.sn_name if row.source_id
                                else '') or '')

    # payload display columns (non-stored, one per spec key)
    payload_standard_version = fields.Char(
        string='STANDARD_VERSION', compute='_compute_payload_columns',
        store=False)
    payload_production_order_id = fields.Char(
        string='PRODUCTION_ORDER_ID', compute='_compute_payload_columns',
        store=False)
    payload_work_order_code = fields.Char(
        string='WORK_ORDER_CODE', compute='_compute_payload_columns',
        store=False)
    payload_info_type_code = fields.Char(
        string='INFO_TYPE_CODE', compute='_compute_payload_columns',
        store=False)
    payload_device_no = fields.Char(
        string='DEVICE_NO', compute='_compute_payload_columns',
        store=False)
    payload_test_code = fields.Char(
        string='TEST_CODE', compute='_compute_payload_columns',
        store=False)
    payload_model_code = fields.Char(
        string='MODEL_CODE', compute='_compute_payload_columns',
        store=False)
    payload_pcb_code = fields.Char(
        string='PCB_CODE', compute='_compute_payload_columns',
        store=False)
    payload_check_time = fields.Char(
        string='CHECK_TIME', compute='_compute_payload_columns',
        store=False)
    payload_create_time = fields.Char(
        string='CREATE_TIME', compute='_compute_payload_columns',
        store=False)
    payload_upload_time = fields.Char(
        string='UPLOAD_TIME', compute='_compute_payload_columns',
        store=False)
    payload_conclusion = fields.Char(
        string='CONCLUSION', compute='_compute_payload_columns',
        store=False)
    payload_test_name = fields.Char(
        string='TEST_NAME', compute='_compute_payload_columns',
        store=False)
    payload_current_value = fields.Char(
        string='CURRENT_VALUE', compute='_compute_payload_columns',
        store=False)
    payload_warming_zone = fields.Char(
        string='WARMING_ZONE', compute='_compute_payload_columns',
        store=False)
    payload_constant_temperature_zone = fields.Char(
        string='CONSTANT_TEMPERATURE_ZONE', compute='_compute_payload_columns',
        store=False)
    payload_welding_zone = fields.Char(
        string='WELDING_ZONE', compute='_compute_payload_columns',
        store=False)
    payload_cooling_zone = fields.Char(
        string='COOLING_ZONE', compute='_compute_payload_columns',
        store=False)
    payload_preheating_area = fields.Char(
        string='PREHEATING_AREA', compute='_compute_payload_columns',
        store=False)
    payload_agingroom_temperature = fields.Char(
        string='AGINGROOM_TEMPERATURE', compute='_compute_payload_columns',
        store=False)
    payload_standard_value = fields.Char(
        string='STANDARD_VALUE', compute='_compute_payload_columns',
        store=False)
    payload_check_duration = fields.Char(
        string='CHECK_DURATION', compute='_compute_payload_columns',
        store=False)
    payload_testing_voltage = fields.Char(
        string='TESTING_VOLTAGE', compute='_compute_payload_columns',
        store=False)
    payload_leakage_current = fields.Char(
        string='LEAKAGE_CURRENT', compute='_compute_payload_columns',
        store=False)
    payload_allowable_error = fields.Char(
        string='ALLOWABLE_ERROR', compute='_compute_payload_columns',
        store=False)
    payload_real_error = fields.Char(
        string='REAL_ERROR', compute='_compute_payload_columns',
        store=False)
    payload_average_error_type = fields.Char(
        string='AVERAGE_ERROR_TYPE', compute='_compute_payload_columns',
        store=False)
    payload_average_error = fields.Char(
        string='AVERAGE_ERROR', compute='_compute_payload_columns',
        store=False)
    payload_software_version = fields.Char(
        string='SOFTWARE_VERSION', compute='_compute_payload_columns',
        store=False)
    payload_plant_code = fields.Char(
        string='PLANT_CODE', compute='_compute_payload_columns',
        store=False)
    payload_nameplate_code = fields.Char(
        string='NAMEPLATE_CODE', compute='_compute_payload_columns',
        store=False)
    payload_table_no = fields.Char(
        string='TABLE_NO', compute='_compute_payload_columns',
        store=False)
    payload_table_address = fields.Char(
        string='TABLE_ADDRESS', compute='_compute_payload_columns',
        store=False)
    payload_asset_management_no = fields.Char(
        string='ASSET_MANAGEMENT_NO', compute='_compute_payload_columns',
        store=False)
    payload_measured_value = fields.Char(
        string='MEASURED_VALUE', compute='_compute_payload_columns',
        store=False)
    payload_error_value = fields.Char(
        string='ERROR_VALUE', compute='_compute_payload_columns',
        store=False)
    payload_logic_address = fields.Char(
        string='LOGIC_ADDRESS', compute='_compute_payload_columns',
        store=False)
    payload_bureau_num = fields.Char(
        string='BUREAU_NUM', compute='_compute_payload_columns',
        store=False)

    def _compute_payload_columns(self):
        for row in self:
            payload = row.payload or {}
            for fname, key in PAYLOAD_COLUMN_MAP.items():
                value = payload.get(key, '')
                row[fname] = str(value) if value is not None else ''

    @api.model
    def _eip_claim(self, code, amount):
        """Atomically take up to ``amount`` qualified snapshots of one
        interface code, FIFO, flipping them to delivered inside the same
        statement (concurrent gateway fetches can never double-claim),
        then freeze the source collection rows. Returns the claimed
        rows ordered by id."""
        # raw SQL claim: flush this transaction's pending writes first
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sn_wsd_eip_collect_outbox o "
            "SET state = 'delivered', "
            "    delivered_time = (now() AT TIME ZONE 'UTC') "
            "WHERE o.id IN ("
            "  SELECT id FROM sn_wsd_eip_collect_outbox"
            "  WHERE state = 'qualified' AND info_type_code = %s"
            "  ORDER BY id LIMIT %s"
            "  FOR UPDATE SKIP LOCKED) "
            "RETURNING id",
            (code, amount))
        ids = sorted(row[0] for row in self.env.cr.fetchall())
        # the UPDATE bypassed the ORM: drop the model cache
        self.invalidate_model()
        claimed = self.browse(ids)
        claimed._eip_freeze_sources()
        return claimed

    def _eip_freeze_sources(self):
        """Mark the source collection rows delivered and stamp
        upload_time (fire-and-forget delivery per the spec: the gateway
        receiving the response is the end of the story)."""
        sources = self.mapped('source_id').filtered(
            lambda row: row and row.state != 'delivered')
        if sources:
            sources.sudo().write({
                'state': 'delivered',
                'upload_time': fields.Datetime.now(),
            })
