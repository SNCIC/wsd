"""EIP value-extraction mapping (buckets 1 and 2).

Bucket 1 -- test detail items: match sn.wsd.mes.test.result.detail rows
by project name and copy actual_value (device payload items, filled at
the test-result backfill phase).

Bucket 2 -- device zone packets: match reflow/wave zone names inside the
nearest packet and aggregate (max per field, min for the cooling zone).

Bucket 3 (aging window points) is built-in logic, not a mapping source:
1011 rows take their points by device + enter/leave window directly.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# EIP field technical name -> (label, numeric?) for the selection and the
# interface/field matrix below
EIP_VALUE_FIELDS = [
    ('current_value', 'Battery Current (uA)'),
    ('warming_zone', 'Warming Zone (C)'),
    ('constant_temperature_zone', 'Constant Temperature Zone (C)'),
    ('welding_zone', 'Welding Zone (C)'),
    ('cooling_zone', 'Cooling Zone (C)'),
    ('preheating_area', 'Preheating Area (C)'),
    ('agingroom_temperature', 'Aging Room Temperature (C)'),
    ('standard_value', 'Standard Value (C)'),
    ('check_duration', 'Check Duration (s)'),
    ('testing_voltage', 'Testing Voltage (V)'),
    ('leakage_current', 'Leakage Current (mA)'),
    ('average_error_type', 'Average Error Type'),
    ('average_error', 'Average Error'),
    ('allowable_error', 'Allowable Error'),
    ('real_error', 'Real Error'),
    ('software_version', 'Software Version'),
    ('plant_code', 'Plant Code'),
    ('nameplate_code', 'Nameplate Code'),
    ('table_no', 'Table No'),
    ('table_address', 'Table Address'),
    ('asset_management_no', 'Asset Management No'),
    ('measured_value', 'Measured Value (V)'),
    ('error_value', 'Error Value'),
    ('logic_address', 'Logic Address'),
    ('bureau_num', 'Bureau Number'),
]

# Which value fields belong to which interface (spec v2.0 field tables,
# meters 1xxx and collection devices 2xxx); a mapping row may only
# target a field of its own interface.
INTERFACE_FIELDS = {
    '1001': [],
    '1002': ['check_duration', 'testing_voltage', 'leakage_current'],
    '1003': [],
    '1004': ['allowable_error', 'real_error'],
    '1005': ['current_value'],
    '1006': [],
    '1007': ['average_error_type', 'average_error'],
    '1008': [
        'software_version', 'plant_code', 'nameplate_code',
        'table_no', 'table_address', 'asset_management_no',
    ],
    '1009': [
        'warming_zone', 'constant_temperature_zone',
        'welding_zone', 'cooling_zone',
    ],
    '1010': ['preheating_area', 'welding_zone'],
    '1011': ['agingroom_temperature', 'standard_value'],
    '2001': [],
    '2002': [],
    '2003': ['check_duration', 'testing_voltage', 'leakage_current'],
    '2004': ['plant_code', 'logic_address', 'bureau_num'],
    '2005': [],
    '2006': [
        'average_error_type', 'standard_value',
        'measured_value', 'error_value',
    ],
    '2007': ['current_value'],
    '2008': [
        'warming_zone', 'constant_temperature_zone',
        'welding_zone', 'cooling_zone',
    ],
    '2009': ['preheating_area', 'welding_zone'],
    '2010': ['agingroom_temperature', 'standard_value'],
}


class EipValueMapping(models.Model):
    """One row = one EIP field of one interface, fed from one named
    source (test detail project name, or a device zone name)."""
    _name = 'sn.wsd.eip.value.mapping'
    _description = 'EIP Value Extraction Mapping'
    _order = 'info_type_code, eip_field, id'
    _check_company_auto = True
    _transform_fn_cache = {}

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    info_type_code = fields.Char(
        string='EIP Info Type Code', required=True, index=True,
        help='Interface the mapped EIP field belongs to (see the '
             'operation code mapping for the code list).')
    eip_field = fields.Selection(
        selection=EIP_VALUE_FIELDS,
        string='EIP Field', required=True, index=True,
        help='Target value column of the collection row.')
    source_kind = fields.Selection(
        selection=[
            ('detail_item', 'Test Detail Item'),
            ('device_zone', 'Device Zone Packet'),
            ('detail_translate', 'Detail Translation (1007/2006)'),
        ],
        string='Source Kind', required=True,
        help='Test Detail Item: match sn.wsd.mes.test.result.detail by '
             'project name (device payload items). Device Zone Packet: '
             'match reflow/wave zone names in the nearest packet. Detail '
             'Translation: per-line translation of the 1007/2006 '
             'expansion (name + matched upper limit -> type code, test '
             'name and washed value).')
    source_key = fields.Char(
        string='Source Key', required=True,
        help='Project name (test detail items) or zone name (device '
             'zone packets) to match.')
    active = fields.Boolean(default=True, index=True)
    match_up_limit = fields.Char(
        string='Match Up Limit', default='', index=True,
        help='Detail upper limit this mapping targets: distinguishes '
             'same-name detail lines (the two PF=1.0 points of a '
             'three-phase meter). Empty = any line with the name.')
    transform_code = fields.Text(
        string='Transform Code',
        help='Optional full Python function defining '
             'def transform(value, low, up, name, seq, detail) and '
             'returning the target number (None skips the item). Runs '
             'in an isolated namespace at cleansing time; only the six '
             'plain-data arguments are visible.')
    target_type = fields.Char(
        string='Target Type Code',
        help='Detail translation rows: the EIP type code this line '
             'translates to (H1, IA...).')
    target_test_name = fields.Char(
        string='Target Test Name',
        help='Detail translation rows: the EIP test name this line '
             'translates to.')
    sample_value = fields.Char(
        string='Sample Value', store=False,
        help='Trial input for the transform test button.')
    operation_ids = fields.Many2many(
        'sn.wsd.operation',
        string='Operations',
        compute='_compute_operation_ids',
        help='Operations mapped to this interface code (from the EIP '
             'operation code mapping) -- shown beside the code so the '
             'target station is visible while maintaining value keys.')

    @api.depends('info_type_code', 'company_id')
    def _compute_operation_ids(self):
        OpMapping = self.env['sn.wsd.eip.operation.mapping']
        for mapping in self:
            op_maps = OpMapping.search([
                ('info_code', '=', mapping.info_type_code),
                ('company_id', 'in', [mapping.company_id.id, False]),
            ])
            mapping.operation_ids = op_maps.operation_id

    _transform_fn_cache = {}

    def _eip_compile_transform(self):
        """Compile the row's transform_code into a callable, cached by
        (id, write_date). Returns (callable, None) on success or
        (None, error message); no code = (None, None)."""
        self.ensure_one()
        if not self.transform_code:
            return None, None
        key = (self.id, self.write_date)
        cache = type(self)._transform_fn_cache
        fn, err = cache.get(key, (None, None))
        if fn is None and err is None:
            try:
                namespace = {}
                exec(self.transform_code, namespace)
                fn = namespace.get('transform')
                if not callable(fn):
                    err = 'code does not define a callable transform()'
            except Exception as exc:
                err = '%s: %s' % (type(exc).__name__, exc)
            cache[key] = (fn, err)
        return fn, err

    def _eip_call_transform(self, value, low, up, name, seq, detail):
        """Run the row's transform with the standard six-argument
        contract. Returns (number, None) or (None, error); None without
        error means the item is deliberately skipped."""
        fn, err = self._eip_compile_transform()
        if err:
            return None, err
        if fn is None:
            return None, None
        try:
            result = fn(value, low, up, name, seq, detail)
        except Exception as exc:
            return None, '%s: %s' % (type(exc).__name__, exc)
        if result is None:
            return None, None
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            return None, 'transform returned %r, expected a number' % (result,)
        return float(result), None

    def action_test_transform(self):
        """Trial button: run the transform on the pasted sample value
        and show the result without touching any data."""
        self.ensure_one()
        number, err = self._eip_call_transform(
            self.sample_value or '', '', '', self.source_key, 1, {})
        message = ('result = %s' % number) if err is None and number is not None             else ('skipped (None)' if err is None and number is None
                  else 'error: %s' % err)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'message': 'Trial: %s' % message, 'sticky': False},
        }

    _mapping_uniq = models.Constraint(
        'unique(company_id, info_type_code, eip_field, source_key, '
        'match_up_limit)',
        'The interface field already has this source mapping for the '
        'matched upper limit.',
    )

    @api.constrains('transform_code')
    def _check_transform_code(self):
        for mapping in self:
            if mapping.transform_code:
                _, err = mapping._eip_compile_transform()
                if err:
                    raise ValidationError(_(
                        'Transform code error: %s', err))

    @api.constrains('source_kind', 'target_type', 'target_test_name')
    def _check_detail_translate(self):
        for mapping in self:
            if mapping.source_kind == 'detail_translate':
                if not mapping.target_type or not mapping.target_test_name:
                    raise ValidationError(_(
                        'Detail translation rows need a target type code '
                        'and a target test name.'))

    @api.constrains('info_type_code', 'eip_field')
    def _check_interface_field(self):
        for mapping in self:
            allowed = INTERFACE_FIELDS.get(mapping.info_type_code)
            if allowed is None:
                raise ValidationError(_(
                    '%(code)s is not a collectable EIP interface code.',
                    code=mapping.info_type_code))
            if allowed and mapping.eip_field not in allowed:
                raise ValidationError(_(
                    '%(field)s does not belong to interface %(code)s.',
                    field=dict(EIP_VALUE_FIELDS).get(mapping.eip_field),
                    code=mapping.info_type_code))
