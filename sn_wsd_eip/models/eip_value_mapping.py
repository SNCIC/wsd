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
]

# Which value fields belong to which interface (spec v2.0 field tables);
# a mapping row may only target a field of its own interface.
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
}


class EipValueMapping(models.Model):
    """One row = one EIP field of one interface, fed from one named
    source (test detail project name, or a device zone name)."""
    _name = 'sn.wsd.eip.value.mapping'
    _description = 'EIP Value Extraction Mapping'
    _order = 'info_type_code, eip_field, id'
    _check_company_auto = True

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
        ],
        string='Source Kind', required=True,
        help='Test Detail Item: match sn.wsd.mes.test.result.detail by '
             'project name (device payload items). Device Zone Packet: '
             'match reflow/wave zone names in the nearest packet.')
    source_key = fields.Char(
        string='Source Key', required=True,
        help='Project name (test detail items) or zone name (device '
             'zone packets) to match.')
    active = fields.Boolean(default=True, index=True)
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

    _mapping_uniq = models.Constraint(
        'unique(company_id, info_type_code, eip_field, source_key)',
        'The interface field already has this source mapping.',
    )

    @api.constrains('info_type_code', 'eip_field')
    def _check_interface_field(self):
        for mapping in self:
            allowed = INTERFACE_FIELDS.get(mapping.info_type_code)
            if allowed is None:
                raise ValidationError(_(
                    '%(code)s is not a station-collectable EIP interface '
                    'code.', code=mapping.info_type_code))
            if allowed and mapping.eip_field not in allowed:
                raise ValidationError(_(
                    '%(field)s does not belong to interface %(code)s.',
                    field=dict(EIP_VALUE_FIELDS).get(mapping.eip_field),
                    code=mapping.info_type_code))
