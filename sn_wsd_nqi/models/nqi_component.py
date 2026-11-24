from odoo import fields, models


class NqiComponent(models.Model):
    """NQI PUB_COMPONENT_INFO mirror, preloaded from the NQI-issued
    public info workbook. Component codes are referenced by the meter
    component binding table and the purchase chapter rows."""
    _name = 'sn.wsd.nqi.component'
    _inherit = ['sn.wsd.nqi.dictionary.mixin']
    _description = 'NQI Component Info'
    _nqi_import_key = ('code',)
    _order = 'code, id'
    _rec_name = 'name'

    name = fields.Char(string='Name', required=True, index=True)
    code = fields.Char(string='Code', required=True, index=True)
    type_code = fields.Char(string='Type Code', index=True)
    model_code = fields.Char(string='Model Code')
    spec_code = fields.Char(string='Spec Code')
    performance_parameter_code = fields.Char(
        string='Performance Parameter Code')
    supplier_enterprise_code = fields.Char(
        string='Supplier Enterprise Code',
        help='Plain char mirror: the enterprise dictionary itself is not '
             'imported (out of scope by decision).')
    note = fields.Char(string='Note')

    _code_uniq = models.Constraint(
        'unique(code)',
        'Component code must be unique.',
    )
