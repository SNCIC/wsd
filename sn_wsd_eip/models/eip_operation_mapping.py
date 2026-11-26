from odoo import _, fields, models


class EipOperationMapping(models.Model):
    """Standard operation -> EIP interface code (INFO_TYPE_CODE).

    Only operations mapped here produce EIP collection rows at station
    pass. The mapping carries the spec family dimension: the same
    operation (an AOI station, say) gets 1001 on the electricity-meter
    line and 2001 on the collection-device line, chosen per product at
    capture time. Legacy single-family setups keep one meter row.
    """
    _name = 'sn.wsd.eip.operation.mapping'
    _description = 'EIP Operation Code Mapping'
    _order = 'info_code, id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='Operation',
        required=True,
        index=True,
        ondelete='cascade',
        check_company=True,
    )
    family = fields.Selection(
        selection=[
            ('meter', 'Electricity Meter'),
            ('collector', 'Collection Device'),
        ],
        string='Device Category', required=True, default='meter', index=True,
        help='Production-data spec the code belongs to: electricity '
             'meter (1xxx) or collection device (2xxx).')
    info_code = fields.Char(
        string='EIP Info Type Code',
        required=True,
        index=True,
        help='INFO_TYPE_CODE: electricity meters 1001 AOI, 1002 '
             'withstand voltage, 1003 FCT, 1004 daily timing error, '
             '1005 battery current, 1006 basic error, 1007 basic error '
             'detail, 1008 parameter setting, 1009 reflow, 1010 wave '
             'soldering, 1011 high-temp aging; collection devices '
             '2001..2010 mirror the same stations.')
    active = fields.Boolean(default=True, index=True)
    note = fields.Char(string='Notes')

    _operation_uniq = models.Constraint(
        'unique(company_id, operation_id, family)',
        'The operation already has an EIP code mapping for this spec '
        'family.',
    )
