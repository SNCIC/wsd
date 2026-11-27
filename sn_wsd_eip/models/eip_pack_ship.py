"""Packing-storage and shipping records (manual-entry interfaces
1090/2090 and 1091/2091).

Two separate documents on purpose (user decision 2026-11-26):

- packing storage: ONE record per stored unit -- each row carries one
  grid nameplate number;
- shipping: ONE record per shipment batch -- a continuous nameplate
  range (start..final) plus the shipped count.

They are logistics documents, not station inspections: no cleansing
gates, no snapshots -- the gateway serves them directly from these
tables (FIFO claim, delivered on serve, exact spec payloads). Required
fields are enforced at entry; import flows through the same editable
lists.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EipPackRecord(models.Model):
    """Packing storage: one record per stored unit (1090 / 2090)."""
    _name = 'sn.wsd.eip.pack.record'
    _description = 'EIP Packing Storage Record'
    _order = 'id'
    _rec_name = 'test_code'
    _check_company_auto = True
    # overview page: the rows of one work order of one company
    _work_order_idx = models.Index('(company_id, work_order_no)')

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    info_type_code = fields.Selection(
        selection=[('1090', 'Packing Storage (Meter)'),
                   ('2090', 'Packing Storage (Collector)')],
        string='Info Type Code', required=True, index=True)
    family = fields.Selection(
        selection=[('meter', 'Electricity Meter'),
                   ('collector', 'Collection Device')],
        string='Device Category', compute='_compute_family', store=True,
        index=True)
    production_order_no = fields.Char(string='Production Order No.',
                                      required=True)
    work_order_no = fields.Char(string='Work Order No.', required=True)
    # capture link: the nameplate-to-machine binding this row was born
    # from (empty on a row entered by hand)
    binding_id = fields.Many2one(
        'sn.wsd.serial.binding', string='Nameplate Binding',
        ondelete='restrict', index=True, copy=False)
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='Machine SN',
        ondelete='restrict', index=True, copy=False)
    test_code = fields.Char(
        string='Serial No.', required=True, index=True,
        help='Unique ID generated per storage event.')
    model_code = fields.Char(string='Model Code', required=True)
    nameplate_code = fields.Char(
        string='Grid Nameplate No.', required=True,
        help='Grid device number of the stored unit (实物ID).')
    number = fields.Integer(string='Number', required=True, default=1)
    unit = fields.Char(
        string='Unit', required=True,
        help='Meter: 只; collection device: 台.')
    storage_date = fields.Date(string='Storage Date', required=True)
    conclusion = fields.Integer(
        string='Conclusion', required=True, default=0,
        help='0 pass, 1 fail.')
    state = fields.Selection(
        selection=[('pending', 'Pending'), ('delivered', 'Delivered')],
        string='State', required=True, default='pending', index=True)
    delivered_time = fields.Datetime(string='Delivered Time', readonly=True)

    _binding_uniq = models.Constraint(
        'unique(company_id, binding_id)',
        'The same nameplate binding can only be collected once.',
    )

    # spec family -> interface code / unit of the packing-storage rows
    PACK_CODE = {'meter': '1090', 'collector': '2090'}
    PACK_UNIT = {'meter': '只', 'collector': '台'}

    @api.model
    def _eip_capture_from_bindings(self, bindings):
        """One pending packing-storage row per nameplate binding: the
        nameplate SN of the binding is the stored unit's grid nameplate
        number, the machine SN supplies the production order, the work
        order and the model (its latest pass). SNs without a production
        order or without a mapped spec family are skipped -- nothing is
        invented for them; the by-work-order wizard reports the gap."""
        bindings = bindings.filtered(
            lambda binding: binding.binding_type == 'nameplate')
        bindings -= self.sudo().search(
            [('binding_id', 'in', bindings.ids)]).binding_id
        if not bindings:
            return self
        histories = self.env['sn.wsd.serial.operation.history'].sudo().search(
            [('serial_identity_id', 'in',
              bindings.bound_serial_identity_id.ids)],
            order='out_date desc, id desc')
        latest = {}
        for history in histories:
            latest.setdefault(history.serial_identity_id, history)
        resolver = self.env['sn.wsd.eip.pass.record']
        records = self
        for binding in bindings:
            history = latest.get(binding.bound_serial_identity_id)
            order = history and history.mes_order_id
            production = order and order.production_id
            if not production:
                continue
            family = resolver._eip_resolve_family(
                order.product_id, binding.company_id)
            if not family:
                continue
            records |= self.create({
                'company_id': binding.company_id.id,
                'info_type_code': self.PACK_CODE[family],
                'production_order_no': production.name,
                'work_order_no': order.name,
                'binding_id': binding.id,
                'serial_identity_id': binding.bound_serial_identity_id.id,
                'test_code': '%s-%s' % (self.PACK_CODE[family],
                                        binding.id),
                'model_code': (order.product_id.material_specification
                               or order.product_id.default_code),
                'nameplate_code': binding.serial_identity_id.name,
                'number': 1,
                'unit': self.PACK_UNIT[family],
                'storage_date': fields.Date.to_date(
                    binding.binding_date),
            })
        return records

    @api.depends('info_type_code')
    def _compute_family(self):
        for record in self:
            record.family = ('meter'
                             if (record.info_type_code or '1').startswith('1')
                             else 'collector')

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

    def _eip_claim(self, code, amount):
        """Atomically take up to ``amount`` pending records of one code,
        FIFO, delivering them inside the same statement."""
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sn_wsd_eip_pack_record r "
            "SET state = 'delivered', "
            "    delivered_time = (now() AT TIME ZONE 'UTC') "
            "WHERE r.id IN ("
            "  SELECT id FROM sn_wsd_eip_pack_record"
            "  WHERE state = 'pending' AND info_type_code = %s"
            "  ORDER BY id LIMIT %s"
            "  FOR UPDATE SKIP LOCKED) "
            "RETURNING id",
            (code, amount))
        ids = sorted(row[0] for row in self.env.cr.fetchall())
        self.invalidate_model()
        return self.browse(ids)

    def _eip_pack_payloads(self):
        """Exact spec field list of 1090/2090."""
        payloads = []
        for record in self:
            payloads.append({
                'STANDARD_VERSION': 2,
                'PRODUCTION_ORDER_ID': record.production_order_no or '',
                'WORK_ORDER_CODE': record.work_order_no or '',
                'INFO_TYPE_CODE': record.info_type_code or '',
                'TEST_CODE': record.test_code or '',
                'MODEL_CODE': record.model_code or '',
                'NAMEPLATE_CODE': record.nameplate_code or '',
                'CREATE_TIME': _fmt_dt(record.create_date),
                'UPLOAD_TIME': _fmt_dt(record.delivered_time),
                'NUMBER': int(record.number or 0),
                'UNIT': record.unit or '',
                'STORAGE_TIME': _fmt_date(record.storage_date),
                'CONCLUSION': int(record.conclusion or 0),
            })
        return payloads


class EipShipRecord(models.Model):
    """Finished-goods shipping: one record per shipment batch, covering
    a continuous nameplate range (1091 / 2091)."""
    _name = 'sn.wsd.eip.ship.record'
    _description = 'EIP Shipping Record'
    _order = 'id'
    _rec_name = 'test_code'
    _check_company_auto = True
    # overview page: the rows of one work order of one company
    _work_order_idx = models.Index('(company_id, work_order_no)')

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    info_type_code = fields.Selection(
        selection=[('1091', 'Shipping (Meter)'),
                   ('2091', 'Shipping (Collector)')],
        string='Info Type Code', required=True, index=True)
    family = fields.Selection(
        selection=[('meter', 'Electricity Meter'),
                   ('collector', 'Collection Device')],
        string='Device Category', compute='_compute_family', store=True,
        index=True)
    production_order_no = fields.Char(string='Production Order No.',
                                      required=True)
    work_order_no = fields.Char(string='Work Order No.', required=True)
    test_code = fields.Char(
        string='Serial No.', required=True, index=True,
        help='Unique ID generated per shipping event.')
    model_code = fields.Char(string='Model Code', required=True)
    nameplate_start = fields.Char(
        string='Nameplate Start', required=True,
        help='Grid device number range start; * for random codes.')
    nameplate_final = fields.Char(
        string='Nameplate Final', required=True,
        help='Grid device number range end; * for random codes.')
    number = fields.Integer(string='Number', required=True)
    unit = fields.Char(
        string='Unit', required=True,
        help='Meter: 只; collection device: 台.')
    deliver_date = fields.Date(string='Deliver Date', required=True)
    deliver_status = fields.Selection(
        selection=[('0', 'Not Shipped'), ('1', 'Shipped')],
        string='Deliver Status', required=True, default='0')
    state = fields.Selection(
        selection=[('pending', 'Pending'), ('delivered', 'Delivered')],
        string='State', required=True, default='pending', index=True)
    delivered_time = fields.Datetime(string='Delivered Time', readonly=True)

    @api.depends('info_type_code')
    def _compute_family(self):
        for record in self:
            record.family = ('meter'
                             if (record.info_type_code or '1').startswith('1')
                             else 'collector')

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

    def _eip_claim(self, code, amount):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sn_wsd_eip_ship_record r "
            "SET state = 'delivered', "
            "    delivered_time = (now() AT TIME ZONE 'UTC') "
            "WHERE r.id IN ("
            "  SELECT id FROM sn_wsd_eip_ship_record"
            "  WHERE state = 'pending' AND info_type_code = %s"
            "  ORDER BY id LIMIT %s"
            "  FOR UPDATE SKIP LOCKED) "
            "RETURNING id",
            (code, amount))
        ids = sorted(row[0] for row in self.env.cr.fetchall())
        self.invalidate_model()
        return self.browse(ids)

    def _eip_ship_payloads(self):
        """Exact spec field list of 1091/2091 (no CONCLUSION field)."""
        payloads = []
        for record in self:
            payloads.append({
                'STANDARD_VERSION': 2,
                'PRODUCTION_ORDER_ID': record.production_order_no or '',
                'WORK_ORDER_CODE': record.work_order_no or '',
                'INFO_TYPE_CODE': record.info_type_code or '',
                'TEST_CODE': record.test_code or '',
                'MODEL_CODE': record.model_code or '',
                'NAMEPLATE_CODE_START': record.nameplate_start or '',
                'NAMEPLATE_CODE_FINAL': record.nameplate_final or '',
                'CREATE_TIME': _fmt_dt(record.create_date),
                'UPLOAD_TIME': _fmt_dt(record.delivered_time),
                'NUMBER': int(record.number or 0),
                'UNIT': record.unit or '',
                'DELIVER_TIME': _fmt_date(record.deliver_date),
                'DELIVER_STATUS': record.deliver_status or '0',
            })
        return payloads


def _fmt_dt(value):
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else ''


def _fmt_date(value):
    return value.strftime('%Y-%m-%d') if value else ''
