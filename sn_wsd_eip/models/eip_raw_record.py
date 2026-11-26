"""Raw-material inspection records (manual-entry interfaces
1012..1018 meter and 2011..2014 collector).

One record per raw-material inspection of one batch: the spec value
fields are generic (value + error_value) -- the payload maps the value
onto the interface's own spec key (VARISTOR_VOLTAGE / RATIO_VALUE /
FREQUENCY_VALUE / VOLTAGE_VALUES / LEAKAGE_CURRENT / CONTRAST_VALUE).

Not station-pass data: served directly from this table (FIFO claim,
delivered on serve) like the packing/shipping and report interfaces.
Required fields are enforced at entry/import; no cleansing gates.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

# per-code spec key of the generic value column
RAW_VALUE_KEY = {
    '1012': 'VARISTOR_VOLTAGE',
    '2011': 'VARISTOR_VOLTAGE',
    '1013': 'RATIO_VALUE',
    '2012': 'RATIO_VALUE',
    '1014': 'FREQUENCY_VALUE',
    '2013': 'FREQUENCY_VALUE',
    '1015': 'LEAKAGE_CURRENT',
    '2014': 'LEAKAGE_CURRENT',
    '1016': 'VOLTAGE_VALUES',
    '1018': 'CONTRAST_VALUE',
    # 1017 液晶: conclusion only, no value field
}
RAW_VALUE_KIND = {
    'VARISTOR_VOLTAGE': 1,
    'RATIO_VALUE': 1,
    'FREQUENCY_VALUE': 1,
    'VOLTAGE_VALUES': 3,
    'LEAKAGE_CURRENT': 3,
    'CONTRAST_VALUE': 3,
}


def _fmt_dt(value):
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else ''


def _fmt_date(value):
    return value.strftime('%Y-%m-%d') if value else ''


class EipRawRecord(models.Model):
    _name = 'sn.wsd.eip.raw.record'
    _description = 'EIP Raw Material Inspection Record'
    _order = 'id'
    _rec_name = 'test_code'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    info_type_code = fields.Selection(
        selection=[('1012', '压敏电阻'), ('1013', '光电耦合器'),
                   ('1014', '晶体谐振器'), ('1015', '瞬变二极管'),
                   ('1016', '时钟电池'), ('1017', '液晶'),
                   ('1018', '电流互感器'),
                   ('2011', '压敏电阻'), ('2012', '光电耦合器'),
                   ('2013', '晶体谐振器'), ('2014', '瞬变二极管')],
        string='Info Type Code', required=True, index=True)
    family = fields.Selection(
        selection=[('meter', 'Electricity Meter'),
                   ('collector', 'Collection Device')],
        string='Spec Family', compute='_compute_family', store=True,
        index=True)
    production_order_no = fields.Char(string='Production Order No.',
                                      required=True)
    work_order_no = fields.Char(string='Work Order No.', required=True)
    material_check_batch = fields.Char(
        string='Material Check Batch', required=True,
        help='Raw-material inspection batch of our side.')
    material_batch = fields.Char(
        string='Material Batch', required=True,
        help='Batch number of the manufacturer.')
    material_brand = fields.Char(
        string='Material Brand', required=True,
        help='Brand full name, or the agent full name when unbranded.')
    material_supplier = fields.Char(
        string='Material Manufacturer', required=True,
        help='Manufacturer full name of the raw material.')
    material_leave_date = fields.Date(
        string='Material Leave Date', required=True,
        help='Manufacturer leave date; weekly dates become Monday.')
    incoming_check_date = fields.Date(
        string='Incoming Check Date', required=True)
    test_code = fields.Char(
        string='Test Code', required=True, index=True,
        help='Unique ID per inspection.')
    model_code = fields.Char(string='Model Code', required=True)
    check_time = fields.Datetime(string='Check Time', required=True)
    value = fields.Float(
        string='Inspection Value', digits=(10, 3),
        help='The measured value of this inspection; lands on the '
             'interface-specific spec key of the payload.')
    error_value = fields.Float(
        string='Error Value', digits=(10, 3),
        help='1012/2011 only: the error of the varistor voltage.')
    conclusion = fields.Integer(
        string='Conclusion', required=True, default=0,
        help='0 pass, 1 fail.')
    state = fields.Selection(
        selection=[('pending', 'Pending'), ('delivered', 'Delivered')],
        string='State', required=True, default='pending', index=True)
    delivered_time = fields.Datetime(string='Delivered Time', readonly=True)

    # the only columns the delivery stamp itself may write on an
    # already-delivered row -- everything else is frozen forever
    DELIVERY_WRITE_KEYS = frozenset({'state', 'delivered_time'})

    def write(self, vals):
        if (any(record.state == 'delivered' for record in self)
                and any(key not in self.DELIVERY_WRITE_KEYS
                        for key in vals)):
            raise UserError(_(
                'Delivered rows are frozen: the gateway already took '
                'them, nothing can be edited afterwards.'))
        return super().write(vals)

    @api.depends('info_type_code')
    def _compute_family(self):
        for record in self:
            record.family = ('meter'
                             if (record.info_type_code or '1').startswith('1')
                             else 'collector')

    def _eip_claim(self, code, amount):
        """Atomically take up to ``amount`` pending records of one code,
        FIFO, delivering them inside the same statement."""
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sn_wsd_eip_raw_record r "
            "SET state = 'delivered', "
            "    delivered_time = (now() AT TIME ZONE 'UTC') "
            "WHERE r.id IN ("
            "  SELECT id FROM sn_wsd_eip_raw_record"
            "  WHERE state = 'pending' AND info_type_code = %s"
            "  ORDER BY id LIMIT %s"
            "  FOR UPDATE SKIP LOCKED) "
            "RETURNING id",
            (code, amount))
        ids = sorted(row[0] for row in self.env.cr.fetchall())
        self.invalidate_model()
        return self.browse(ids)

    def _eip_raw_payloads(self):
        """Exact spec field list of 1012..1018 / 2011..2014."""
        payloads = []
        for record in self:
            payload = {
                'STANDARD_VERSION': 2,
                'PRODUCTION_ORDER_ID': record.production_order_no or '',
                'WORK_ORDER_CODE': record.work_order_no or '',
                'INFO_TYPE_CODE': record.info_type_code or '',
                'MATERIAL_CHECK_BATCH': record.material_check_batch or '',
                'MATERIAL_BATCH': record.material_batch or '',
                'MATERIAL_BRAND': record.material_brand or '',
                'MATERIAL_SUPPLIER': record.material_supplier or '',
                'MATERIAL_LEAVE_TIME': _fmt_date(record.material_leave_date),
                'INCOMING_CHECK_TIME': _fmt_date(record.incoming_check_date),
                'TEST_CODE': record.test_code or '',
                'MODEL_CODE': record.model_code or '',
                'CHECK_TIME': _fmt_dt(record.check_time),
                'CREATE_TIME': _fmt_dt(record.create_date),
                'UPLOAD_TIME': _fmt_dt(record.delivered_time),
                'CONCLUSION': int(record.conclusion or 0),
            }
            key = RAW_VALUE_KEY.get(record.info_type_code)
            if key:
                kind = RAW_VALUE_KIND[key]
                value = float(record.value or 0.0)
                payload[key] = (round(value, 1) if kind == 1
                                else round(value, 3))
            if record.info_type_code in ('1012', '2011'):
                payload['ERROR_VALUE'] = round(
                    float(record.error_value or 0.0), 3)
            payloads.append(payload)
        return payloads
