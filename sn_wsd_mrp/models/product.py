from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .constants import BOARD_SIDE_SELECTION


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


class ProductProduct(models.Model):
    _inherit = 'product.product'

    material_specification = fields.Char(
        related='product_tmpl_id.material_specification',
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

    @api.model_create_multi
    def create(self, vals_list):
        # 抑制模板约束在 related 逐字段写回的中间态触发（见
        # ProductTemplate._check_board_side_declared），创建完成后复检。
        products = super(ProductProduct, self.with_context(
            sn_wsd_suppress_board_side_check=True)).create(vals_list)
        products.with_context(
            sn_wsd_suppress_board_side_check=False,
        ).mapped('product_tmpl_id')._check_board_side_declared()
        return products
