import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .constants import BOARD_SIDE_SELECTION


class SnWsdBrand(models.Model):
    """Brand master data used on the products and printed on the documents.

    A brand is shared by every company: the trade mark a material is sold
    under, not the maker of the material. The maker of a supplied material
    is kept on the partner instead (res.partner.manufacturer).
    """

    _name = 'sn.wsd.brand'
    _description = 'Product Brand'
    _order = 'sequence, name'

    name = fields.Char(
        string='Brand Name',
        required=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        'unique (name)',
        'Brand name already exists!',
    )


class ProductCategory(models.Model):
    _inherit = 'product.category'

    x_is_reel_material = fields.Boolean(
        string='Reel Material',
        help='Electronic reel materials: products under this category '
             '(children included) are issued and returned as whole reels '
             '(the current lot balance at the source location) instead of '
             'the exact demand quantity.',
    )

    @api.model
    def _reel_material_category_ids(self):
        """Ids of every category flagged as a reel material category, the
        flagged categories and their descendants included."""
        marked = self.search([('x_is_reel_material', '=', True)])
        if not marked:
            return set()
        return set(self.search([('id', 'child_of', marked.ids)]).ids)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    material_specification = fields.Char(
        string='Material Specification',
        tracking=True,
    )
    mnemonic_code = fields.Char(
        string='Mnemonic Code',
        tracking=True,
        help='Short code used to recognise the material at a glance.',
    )
    brand_id = fields.Many2one(
        comodel_name='sn.wsd.brand',
        string='Brand',
        tracking=True,
        help='Brand of the material, printed on the purchase contract.',
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
    x_use_daily_plan = fields.Boolean(
        string='Use Daily Plan',
        default=False,
        help='If checked, manufacturing orders for this product are split into '
             'daily MES orders instead of backorders.',
    )
    # ------------------------------------------------------------------
    # SMT board side (板面类型) -- the source of truth for side-based route
    # matching (车间 + 图号 + 面别). The matching itself lives on
    # mrp.production (工艺路线检查视图) and the scheduling wizard, never on
    # the product: without the board side, "no B-side route" is
    # indistinguishable from "this board is single-sided".
    # ------------------------------------------------------------------
    x_board_side = fields.Selection(
        BOARD_SIDE_SELECTION,
        string='Board Side Type',
        default='single',
        tracking=True,
        help='Single: one single-side process route. Double: one Top (T) and '
             'one Bottom (B) process route, scheduled independently per side. '
             'Defaults to Single; switch to Double for double-sided boards.',
    )

    # 图号唯一载体是原生内部参考 default_code（界面显示"图号"），不再有
    # 单独的 Drawing No. 字段。
    #
    # 板面类型是面别排产的源头（设计文档 1.2 required）：有图号必须声明。
    # 产品变体上的 default_code / x_board_side 是可写 related，创建变体时
    # 它们逐个写回模板，约束若在中间态触发会误报；因此变体创建期间用
    # 上下文标记抑制，创建完成后在 ProductProduct.create 里显式复检。
    @api.constrains('default_code', 'x_board_side')
    def _check_board_side_declared(self):
        if self.env.context.get('sn_wsd_suppress_board_side_check'):
            return
        for template in self:
            if template.default_code and not template.x_board_side:
                raise ValidationError(_(
                    'Products with a drawing number must declare their board '
                    'side type (single or double).'))

    @api.model
    def _check_classification(self, vals_list):
        """A product must be classified and carry its material code as soon as
        it is created. Multi-variant templates keep their code on the variants
        instead, so the material code is only required when no attribute line
        is provided."""
        for vals in vals_list:
            if not vals.get('categ_id'):
                raise ValidationError(_('The product category is required.'))
            if not vals.get('default_code') and not vals.get('attribute_line_ids'):
                raise ValidationError(_('The material code is required.'))

    @api.model_create_multi
    def create(self, vals_list):
        # The rule is checked on the template creation (product form, imports),
        # which is the only place carrying the category and the material code
        # together. A variant creation builds its template first while
        # default_code stays on the variant, so the template never sees the
        # code: ProductProduct.create opts out through the context.
        if not self.env.context.get('sn_wsd_suppress_classification_check'):
            self._check_classification(vals_list)
        return super().create(vals_list)

    def copy(self, default=None):
        """Give a duplicated product the next free material code.

        default_code is a computed field, so copy() does not carry it over.
        Without a generated value the required check above would refuse the
        duplicate; the new code keeps the prefix and increments the trailing
        number from the highest one already used with that prefix.
        """
        self.ensure_one()
        default = dict(default or {})
        if not default.get('default_code') and self.default_code:
            default['default_code'] = self._next_material_code(self.default_code)
        return super().copy(default=default)

    @api.model
    def _next_material_code(self, code):
        """Next code inside the same series, e.g. E.08.001.0010 -> E.08.001.0024.

        Material codes are numbered per series: the leading digit of the last
        numeric segment selects the series (E.08.001.0xxx, E.08.001.1xxx,
        ...), the remaining digits are the counter. The counter continues
        from the highest one already used in that series, keeping its width.
        """
        match = re.match(r'^(.*?)(\d+)$', code or '')
        if not match:
            return False
        prefix, digits = match.groups()
        if len(digits) > 1:
            series_prefix = prefix + digits[0]
            counter = digits[1:]
        else:
            series_prefix = prefix
            counter = digits
        width = len(counter)
        numbers = []
        for candidate in self.sudo().search(
                [('default_code', '=like', series_prefix + '%')]).mapped('default_code'):
            suffix = candidate[len(series_prefix):]
            if (candidate.startswith(series_prefix)
                    and suffix.isdigit()
                    and len(suffix) == width):
                numbers.append(int(suffix))
        next_number = max(numbers + [int(counter or 0)]) + 1
        for _attempt in range(1000):
            candidate = series_prefix + str(next_number).zfill(width)
            if not self.sudo().search_count([('default_code', '=', candidate)]):
                return candidate
            next_number += 1
        return False


class ProductProduct(models.Model):
    _inherit = 'product.product'

    material_specification = fields.Char(
        related='product_tmpl_id.material_specification',
        store=True,
        readonly=False,
    )
    mnemonic_code = fields.Char(
        related='product_tmpl_id.mnemonic_code',
        store=True,
        readonly=False,
    )
    brand_id = fields.Many2one(
        related='product_tmpl_id.brand_id',
        string='Brand',
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
    x_board_side = fields.Selection(
        related='product_tmpl_id.x_board_side',
        store=True,
        readonly=False,
    )
    x_use_daily_plan = fields.Boolean(
        related='product_tmpl_id.x_use_daily_plan',
        store=True,
    )

    def _is_reel_material(self):
        """True for electronic reel materials: the product belongs to a
        category (or one of its descendants) flagged as a reel material
        category. Only these move whole reels on material issues and
        returns; every other material moves the exact demand quantity."""
        self.ensure_one()
        reel_category_ids = self.env[
            'product.category']._reel_material_category_ids()
        return bool(reel_category_ids) and self.categ_id.id in reel_category_ids

    @api.model_create_multi
    def create(self, vals_list):
        # 抑制模板约束在 related 逐字段写回的中间态触发（见
        # ProductTemplate._check_board_side_declared），创建完成后复检。
        # 一并跳过模板的分类/物料编码校验：变体创建会先建模板，而
        # default_code 落在变体上，模板侧永远拿不到编码；分类与编码只有
        # 直接建模板（产品表单、导入）时才是成对出现的。
        products = super(ProductProduct, self.with_context(
            sn_wsd_suppress_board_side_check=True,
            sn_wsd_suppress_classification_check=True,
        )).create(vals_list)
        products.with_context(
            sn_wsd_suppress_board_side_check=False,
        ).mapped('product_tmpl_id')._check_board_side_declared()
        return products
