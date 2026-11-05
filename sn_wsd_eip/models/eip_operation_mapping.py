from odoo import _, fields, models


class EipOperationMapping(models.Model):
    """Standard operation -> EIP interface code (INFO_TYPE_CODE).

    Only operations mapped here produce EIP collection rows at station
    pass. The code namespace is the electricity-meter EIP spec v2.0
    (1001..1011, station-collectable interfaces). The aging-room spec for
    collection devices (2xxx) is deliberately out of scope; should it be
    needed later, a spec dimension column can be added to this table.
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
    info_code = fields.Char(
        string='EIP Info Type Code',
        required=True,
        index=True,
        help='INFO_TYPE_CODE of the electricity-meter EIP spec v2.0: '
             '1001 AOI, 1002 withstand voltage, 1003 FCT, 1004 daily '
             'timing error, 1005 battery current, 1006 basic error, '
             '1007 basic error detail, 1008 parameter setting, 1009 '
             'reflow, 1010 wave soldering, 1011 high-temp aging.')
    active = fields.Boolean(default=True, index=True)
    note = fields.Char(string='Notes')

    _operation_uniq = models.Constraint(
        'unique(company_id, operation_id)',
        'The operation already has an EIP code mapping.',
    )
