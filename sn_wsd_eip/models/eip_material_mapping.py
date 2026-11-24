from odoo import fields, models


class EipMaterialMapping(models.Model):
    """Company-scoped EIP material code -> our material description.

    Purchase orders only carry the EIP material code and description
    while production orders also need our code, name, unit and
    description; this table carries the translation between them.
    """
    _name = 'sn.wsd.eip.material.mapping'
    _description = 'EIP Material Mapping'
    _rec_name = 'eip_material_code'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    eip_material_code = fields.Char(
        string='EIP Material Code', required=True, index=True,
        help='Material code issued by the EIP platform.')
    material_code = fields.Char(string='Material Code')
    material_name = fields.Char(string='Material Name')
    material_desc = fields.Char(string='Material Description')
    material_unit = fields.Char(string='Material Unit')
    product_model = fields.Char(string='Product Model')
    subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='EIP Subclass', index=True,
        help='Product family of this EIP material: electricity meter '
             '(30002) or collection device (30001). Collection rows are '
             'captured under the matching production-data spec via this '
             'column; rows of unmapped products stay out of the gateway '
             'until the mapping is maintained.')

    _company_material_uniq = models.Constraint(
        'unique(company_id, eip_material_code)',
        'The EIP material code must be unique per company.',
    )
