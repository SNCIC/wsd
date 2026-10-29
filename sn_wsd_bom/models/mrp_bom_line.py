from odoo import fields, models


class MrpBomLine(models.Model):
    """Parent information carried down to the component lines.

    The BOM details list shows every component line on its own row, the way the
    Kingdee BOM detail list does: the columns of the parent BOM are printed on
    the first line of that BOM only. Storing the related values keeps the list
    sortable, groupable and searchable on the parent columns.
    """

    _inherit = 'mrp.bom.line'

    bom_code = fields.Char(
        string='BOM Version',
        related='bom_id.code',
        store=True,
        index=True,
        readonly=True,
    )
    bom_version = fields.Integer(
        string='Version',
        related='bom_id.version',
        store=True,
        readonly=True,
    )
    bom_active = fields.Boolean(
        string='Data Status',
        related='bom_id.active',
        store=True,
        index=True,
        readonly=True,
        help='Production ready BOMs are active, superseded ones are archived.',
    )
    parent_product_code = fields.Char(
        string='Parent Product Code',
        related='bom_id.product_tmpl_id.default_code',
        store=True,
        index=True,
        readonly=True,
    )
    # Not stored: the product name is translatable, a stored related field
    # would keep the value of the language used when the line was written.
    parent_product_name = fields.Char(
        string='Parent Product Name',
        related='bom_id.product_tmpl_id.name',
        readonly=True,
    )
    parent_material_specification = fields.Char(
        string='Parent Specification',
        related='bom_id.material_specification',
        store=True,
        readonly=True,
    )
    categ_id = fields.Many2one(
        'product.category',
        string='BOM Group',
        related='bom_id.product_tmpl_id.categ_id',
        store=True,
        index=True,
        readonly=True,
        help='Product category of the parent product, used as the BOM group '
             'of the details list.',
    )
    workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        related='bom_id.x_workshop_id',
        store=True,
        index=True,
        readonly=True,
    )
