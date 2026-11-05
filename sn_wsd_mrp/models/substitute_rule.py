from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


SUBSTITUTE_SCOPE_SELECTION = [
    ('all', 'All Orders'),
    ('orders', 'Specific Orders'),
]


class SnWsdSubstituteRule(models.Model):
    """替代料规则：主料 → 替代料，默认全局生效，可选限定到指定制令单。

    消费方（上料放行、完工倒冲/报废覆盖、MO 流水回填）统一经
    ``_get_substitute_products`` 判定，不直接读规则行。
    """
    _name = 'sn.wsd.substitute.rule'
    _description = 'Substitute Material Rule'
    _order = 'original_product_id, substitute_product_id, id'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    original_product_id = fields.Many2one(
        'product.product',
        string='Original Product',
        required=True,
        index=True,
        ondelete='restrict',
        check_company=True,
    )
    substitute_product_id = fields.Many2one(
        'product.product',
        string='Substitute Product',
        required=True,
        index=True,
        ondelete='restrict',
        check_company=True,
    )
    original_material_specification = fields.Char(
        string='Original Material Specification',
        related='original_product_id.material_specification',
    )
    substitute_material_specification = fields.Char(
        string='Substitute Material Specification',
        related='substitute_product_id.material_specification',
    )
    scope = fields.Selection(
        SUBSTITUTE_SCOPE_SELECTION,
        string='Scope',
        default='all',
        required=True,
        index=True,
    )
    mes_order_ids = fields.Many2many(
        'sn.wsd.mes.order',
        'sn_wsd_substitute_rule_mes_order_rel',
        'rule_id',
        'mes_order_id',
        string='MES Orders',
    )
    mes_order_count = fields.Integer(string='Orders', compute='_compute_mes_order_count')
    note = fields.Text(string='Note')

    # scope='all' 行受唯一约束（同公司同料号对仅一条全局规则）；
    # 'orders' 行允许同料号对对多张单重复，同对同单去重由 constrains 兜底。
    _scope_pair_uniq = models.Constraint(
        'unique(company_id, original_product_id, substitute_product_id, scope)',
        'A substitute rule already exists for the same product pair and scope.',
    )

    @api.depends(
        'original_product_id.display_name',
        'substitute_product_id.display_name',
    )
    def _compute_name(self):
        for rule in self:
            rule.name = '%s → %s' % (
                rule.original_product_id.display_name or '',
                rule.substitute_product_id.display_name or '',
            )

    @api.depends('mes_order_ids')
    def _compute_mes_order_count(self):
        for rule in self:
            rule.mes_order_count = len(rule.mes_order_ids)

    @api.constrains('original_product_id', 'substitute_product_id')
    def _check_products_differ(self):
        for rule in self:
            if rule.original_product_id and rule.original_product_id == rule.substitute_product_id:
                raise ValidationError(_('A product cannot substitute for itself.'))

    @api.constrains('scope', 'mes_order_ids', 'company_id')
    def _check_scope_orders(self):
        for rule in self:
            if rule.scope != 'orders':
                continue
            if not rule.mes_order_ids:
                raise ValidationError(_(
                    'Select at least one MES order for a rule scoped to specific orders.'))
            foreign = rule.mes_order_ids.filtered(
                lambda order: order.company_id != rule.company_id)
            if foreign:
                raise ValidationError(_(
                    'MES order %(order)s belongs to a different company than the '
                    'substitute rule.', order=foreign[:1].name))

    # ------------------------------------------------------------------
    # 判定 API（上料放行 / 倒冲·报废·流水回填覆盖共用）
    # ------------------------------------------------------------------

    @api.model
    def _get_substitute_products(self, mes_order, original_product):
        """命中 mes_order 的规则下，original_product 允许的替代产品集合。"""
        if not mes_order or not original_product:
            return self.env['product.product']
        rules = self.search([
            ('company_id', '=', mes_order.company_id.id),
            ('original_product_id', '=', original_product.id),
            '|', ('scope', '=', 'all'), ('mes_order_ids', 'in', mes_order.id),
        ])
        return rules.mapped('substitute_product_id')

    @api.model
    def _get_origin_products(self, company, substitute_products, mes_order=False):
        """反查：substitute_products（如已上线的流水产品）按规则可替代的
        主料集合——用于"被替代 BOM 行跳过"的覆盖判定。无 mes_order 上下文
        时仅全局规则命中（单级规则无从判定所属单）。"""
        if not substitute_products:
            return self.env['product.product']
        domain = [
            ('company_id', '=', company.id),
            ('substitute_product_id', 'in', substitute_products.ids),
        ]
        if mes_order:
            domain += ['|', ('scope', '=', 'all'),
                       ('mes_order_ids', 'in', mes_order.id)]
        else:
            domain.append(('scope', '=', 'all'))
        return self.search(domain).mapped('original_product_id')

    @api.model
    def _migrate_product_substitute_rules(self):
        """一次性迁移：产品级替代关系（product_substitute_rel）→ 全局规则。

        幂等：已存在同公司同料号对的全局规则时跳过。双向数据（A→B 与
        B→A 各一行）生成两条规则，语义等价。升级脚本（批 4）调用。
        """
        rules = self
        originals = self.env['product.product'].search(
            [('substitute_ids', '!=', False)])
        for original in originals:
            company = original.company_id or self.env.company
            for substitute in original.substitute_ids:
                if self.search_count([
                    ('company_id', '=', company.id),
                    ('original_product_id', '=', original.id),
                    ('substitute_product_id', '=', substitute.id),
                    ('scope', '=', 'all'),
                ], limit=1):
                    continue
                rules |= self.create({
                    'company_id': company.id,
                    'original_product_id': original.id,
                    'substitute_product_id': substitute.id,
                    'scope': 'all',
                    'note': 'Migrated from product-level substitutes',
                })
        return rules

