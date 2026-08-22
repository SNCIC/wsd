from odoo import _, api, fields, models
from odoo.addons.sn_wsd_mrp.models.constants import (
    BOARD_SIDE_SELECTION,
    SIDE_SELECTION,
)
from odoo.exceptions import ValidationError

MATERIAL_TYPE_SELECTION = [
    ('tooling', 'Tooling'),
    ('consumable', 'Consumable'),
    ('material', 'Material'),
]

# 明细行只落一个 Reference 料号（模型+记录一体），物料类型按引用模型派生。
MATERIAL_REF_SELECTION = [
    ('sn.tooling.template', 'Tooling'),
    ('sn.consumable.template', 'Consumable'),
    ('product.product', 'Material'),
]

REFERENCE_TYPE_MAP = {
    'sn.tooling.template': 'tooling',
    'sn.consumable.template': 'consumable',
    'product.product': 'material',
}


class SnWsdDrawingMaterial(models.Model):
    """Master list of tooling / consumable / material used when a drawing
    number runs through one operation on one production side.

    Dimension: (company, workshop, drawing, operation, side) is unique, so
    no "default" flag is needed. Decoupled from process routes on purpose —
    the list is maintained before any route resolves the drawing.
    """
    _name = 'sn.wsd.drawing.material'
    _description = 'Drawing Material Relation'
    _inherit = ['mail.thread']
    _order = 'x_drawing_no, operation_id, x_side, id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        required=True,
        index=True,
        check_company=True,
        tracking=True,
    )
    x_drawing_no = fields.Char(
        string='Drawing No.',
        required=True,
        index=True,
        tracking=True,
        help='Product code of the drawing; product info is derived from it.',
    )
    operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='Operation',
        required=True,
        index=True,
        check_company=True,
        tracking=True,
    )
    x_side = fields.Selection(
        SIDE_SELECTION,
        string='Production Side',
        required=True,
        tracking=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        compute='_compute_product_info',
    )
    product_name = fields.Char(
        string='Product Name',
        compute='_compute_product_info',
    )
    product_board_side = fields.Selection(
        BOARD_SIDE_SELECTION,
        string='Board Side Type',
        compute='_compute_product_info',
    )
    product_specification = fields.Char(
        string='Product Specification',
        compute='_compute_product_info',
    )
    line_ids = fields.One2many(
        'sn.wsd.drawing.material.line',
        'drawing_material_id',
        string='Material Lines',
        copy=True,
    )
    line_count = fields.Integer(string='Lines', compute='_compute_line_count')
    active = fields.Boolean(default=True)

    # 维度唯一即仲裁：同图号不同面别/工序/车间各自成行，无需"默认"标记。
    _drawing_material_dim_uniq = models.Constraint(
        'unique(company_id, workshop_id, x_drawing_no, operation_id, x_side)',
        'A drawing number already has a material list for this workshop, '
        'operation and side.',
    )

    @api.depends('x_drawing_no')
    def _compute_product_info(self):
        """按图号带出产品信息（与 sn.wsd.process.route.drawing 同口径：
        图号 = product.product.default_code，多匹配取第一条，无匹配留空）。"""
        ProductProduct = self.env['product.product']
        for relation in self:
            product = ProductProduct
            if relation.x_drawing_no:
                product = ProductProduct.search(
                    [('default_code', '=', relation.x_drawing_no)],
                    limit=1,
                )
            relation.product_id = product
            relation.product_name = product.product_tmpl_id.name or False
            relation.product_board_side = product.x_board_side or False
            relation.product_specification = product.material_specification or False

    # 非存储 compute 不随 onchange 自动回传，显式挂 onchange 让新建时
    # 输完图号（失焦）即可看到产品信息，而不是保存后才出现。
    @api.onchange('x_drawing_no')
    def _onchange_drawing_no(self):
        self._compute_product_info()

    @api.depends('line_ids')
    def _compute_line_count(self):
        for relation in self:
            relation.line_count = len(relation.line_ids)

    @api.depends('x_drawing_no', 'operation_id.display_name', 'x_side')
    def _compute_display_name(self):
        # 面别标签取 fields_get 的翻译结果，避免中文界面出现 "Top (T)"。
        side_labels = dict(self.fields_get(['x_side'])['x_side']['selection'])
        for relation in self:
            parts = [
                relation.x_drawing_no or '',
                relation.operation_id.display_name or '',
                side_labels.get(relation.x_side or '', ''),
            ]
            relation.display_name = ' / '.join(part for part in parts if part)


class SnWsdDrawingMaterialLine(models.Model):
    _name = 'sn.wsd.drawing.material.line'
    _description = 'Drawing Material Relation Line'
    _order = 'drawing_material_id, sequence, id'
    _check_company_auto = True

    drawing_material_id = fields.Many2one(
        'sn.wsd.drawing.material',
        string='Drawing Material Relation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    material_type = fields.Selection(
        MATERIAL_TYPE_SELECTION,
        string='Material Type',
        compute='_compute_material_type',
        store=True,
        index=True,
    )
    material_ref = fields.Reference(
        MATERIAL_REF_SELECTION,
        string='Material Code',
        required=True,
        index=True,
    )
    material_name = fields.Char(
        string='Material Name',
        compute='_compute_material_info',
    )
    material_spec = fields.Char(
        string='Material Spec',
        compute='_compute_material_info',
    )
    qty = fields.Float(
        string='Control Quantity',
        required=True,
        default=1.0,
        digits='Product Unit',
    )
    usage_times = fields.Integer(
        string='Usage Times',
        required=True,
        default=1,
        help='How many times the material is consumed per product pass, '
             'e.g. a stencil printing once per board.',
    )
    sequence = fields.Integer(string='Assembly Sequence', default=10)
    note = fields.Text(
        string='Control Note',
        help='Shown to operators at loading-check time (future use).',
    )
    company_id = fields.Many2one(
        'res.company',
        related='drawing_material_id.company_id',
        store=True,
    )

    @api.depends('material_ref')
    def _compute_material_type(self):
        for line in self:
            model = line.material_ref and line.material_ref._name
            line.material_type = REFERENCE_TYPE_MAP.get(model)

    @api.depends('material_ref')
    def _compute_material_info(self):
        for line in self:
            record = line.material_ref
            if not record:
                line.material_name = False
                line.material_spec = False
            elif record._name == 'product.product':
                line.material_name = record.name or False
                line.material_spec = record.material_specification or False
            else:
                line.material_name = record.name or False
                line.material_spec = record.spec or False

    @api.model_create_multi
    def create(self, vals_list):
        # 组立顺序按行序自增：未显式给值时接在当前最大序号后面。
        for vals in vals_list:
            if not vals.get('sequence'):
                parent_id = vals.get('drawing_material_id')
                if parent_id:
                    last = self.search(
                        [('drawing_material_id', '=', parent_id)],
                        order='sequence desc, id desc',
                        limit=1,
                    )
                    vals['sequence'] = (last.sequence + 10) if last else 10
        return super().create(vals_list)

    # 同一清单下同一料号不重复（数据库级）；不同料号可任意多行——
    # 一个图号用两片钢网/两种锡膏是正常场景。
    _material_ref_uniq = models.Constraint(
        'unique(drawing_material_id, material_ref)',
        'This material is already listed on the drawing relation.',
    )

    @api.constrains('qty')
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(_('The control quantity must be positive.'))

    @api.constrains('usage_times')
    def _check_usage_times(self):
        for line in self:
            if line.usage_times < 1:
                raise ValidationError(_(
                    'The usage times must be at least 1.'))
