from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    material_specification = fields.Char(
        string='Material Specification',
        tracking=True,
    )
    abc_class = fields.Selection(
        [
            ('a', 'A'),
            ('b', 'B'),
            ('c', 'C'),
        ],
        string='ABC Class',
        tracking=True,
    )
    is_eip_material = fields.Boolean(
        string='EIP Material',
        tracking=True,
    )
    is_nqi_material = fields.Boolean(
        string='NQI Material',
        tracking=True,
    )
    msd_info = fields.Text(
        string='MSD Information',
    )
    rated_current = fields.Float(
        string='Rated Current',
        tracking=True,
    )
    x_drawing_no = fields.Char(
        string='Drawing No.',
        tracking=True,
    )


class ProductProduct(models.Model):
    _inherit = 'product.product'

    material_specification = fields.Char(
        related='product_tmpl_id.material_specification',
        store=True,
        readonly=False,
    )
    x_drawing_no = fields.Char(
        related='product_tmpl_id.x_drawing_no',
        store=True,
        readonly=False,
    )
    abc_class = fields.Selection(
        related='product_tmpl_id.abc_class',
        store=True,
        readonly=False,
    )
    is_eip_material = fields.Boolean(
        related='product_tmpl_id.is_eip_material',
        store=True,
        readonly=False,
    )
    is_nqi_material = fields.Boolean(
        related='product_tmpl_id.is_nqi_material',
        store=True,
        readonly=False,
    )
    msd_info = fields.Text(
        related='product_tmpl_id.msd_info',
        store=True,
        readonly=False,
    )
    rated_current = fields.Float(
        related='product_tmpl_id.rated_current',
        store=True,
        readonly=False,
    )
