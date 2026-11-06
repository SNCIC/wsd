from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

import logging

_logger = logging.getLogger(__name__)

ORIGIN_SELECTION = [
    ('manual', 'Entered by a User'),
    ('code', 'Matched by Product Code'),
    ('created', 'Product Created in the Buying Company'),
]

# How a source product was turned into a product of the other company.
RESOLUTION_DIRECT = 'direct'
RESOLUTION_MAPPED = 'mapped'
RESOLUTION_CODE = 'code'
RESOLUTION_CREATED = 'created'
RESOLUTION_CREATABLE = 'creatable'
RESOLUTION_TEXT = 'text'


class SnIntercompanyProductMap(models.Model):
    """Product of one company and the product standing for it in another one.

    Since the two companies keep independent catalogues, a product of the
    selling company can never be written on a document of the buying company:
    ``sale.order.line`` and ``account.move.line`` both carry ``check_company``
    on ``product_id``. This mapping is what the synchronization reads, and the
    resolver below is the single place that decides which product of the
    target company a source line becomes.

    The pair is scoped by the two companies rather than by the agreement, so a
    mapping built once keeps working when the trade is driven by the company
    level switches instead of an agreement.
    """

    _name = 'sn.intercompany.product.map'
    _description = 'Inter-Company Product Mapping'
    _order = 'source_company_id, target_company_id, id'

    agreement_id = fields.Many2one(
        'sn.intercompany.agreement', string='Created Under Agreement',
        ondelete='set null', index='btree_not_null',
        help="Agreement the mapping was first created for. Purely informative: "
             "the mapping itself applies to the company pair.")
    direction = fields.Selection(
        [('a_to_b', 'Company A to Company B'),
         ('b_to_a', 'Company B to Company A')],
        string='Trade Direction',
        help="Direction recorded when the mapping was created. The resolution "
             "relies on the source and target companies, not on this field.")
    source_company_id = fields.Many2one(
        'res.company', string='Source Company', required=True, index=True,
        ondelete='cascade')
    target_company_id = fields.Many2one(
        'res.company', string='Target Company', required=True, index=True,
        ondelete='cascade')
    source_product_tmpl_id = fields.Many2one(
        'product.template', string='Source Product',
        required=True, ondelete='cascade', index=True)
    target_product_tmpl_id = fields.Many2one(
        'product.template', string='Target Product',
        ondelete='cascade',
        help="Product used on the documents of the target company. Leave empty "
             "to copy the source product as a text line.")
    origin = fields.Selection(
        ORIGIN_SELECTION, string='Built By', default='manual', required=True,
        help="How this mapping came to exist.")
    uom_ratio = fields.Float(
        string='Unit Ratio', default=1.0,
        help="One unit of the source product equals this many units of the "
             "target product. The quantity of the source line is multiplied by "
             "it, the unit price is divided by it.")
    price_factor = fields.Float(
        string='Price Factor', default=1.0,
        help="Unit price of the source line is multiplied by this factor.")
    active = fields.Boolean(default=True)
    note = fields.Char()

    _product_map_uniq = models.Constraint(
        'UNIQUE(source_company_id, target_company_id, source_product_tmpl_id)',
        'A mapping already exists for this product between these two companies.',
    )

    @api.constrains('source_company_id', 'target_company_id')
    def _check_companies(self):
        for mapping in self:
            if mapping.source_company_id == mapping.target_company_id:
                raise ValidationError(_(
                    "A product mapping needs two different companies."))

    @api.constrains('source_company_id', 'target_company_id',
                    'source_product_tmpl_id', 'target_product_tmpl_id')
    def _check_product_companies(self):
        for mapping in self:
            source_company = mapping.source_product_tmpl_id.company_id
            if source_company and source_company != mapping.source_company_id:
                raise ValidationError(_(
                    "The product \"%(product)s\" belongs to %(company)s and "
                    "cannot be the source of a mapping of %(source)s.",
                    product=mapping.source_product_tmpl_id.display_name,
                    company=source_company.display_name,
                    source=mapping.source_company_id.display_name))
            target_company = mapping.target_product_tmpl_id.company_id
            if target_company and target_company != mapping.target_company_id:
                raise ValidationError(_(
                    "The product \"%(product)s\" belongs to %(company)s and "
                    "cannot be the target of a mapping of %(target)s.",
                    product=mapping.target_product_tmpl_id.display_name,
                    company=target_company.display_name,
                    target=mapping.target_company_id.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('direction') and vals.get('source_company_id') \
                    and vals.get('target_company_id'):
                vals['direction'] = 'a_to_b' \
                    if vals['source_company_id'] < vals['target_company_id'] else 'b_to_a'
        return super().create(vals_list)

    def _mapped_product(self):
        self.ensure_one()
        if not self.target_product_tmpl_id:
            return self.env['product.product']
        return self.target_product_tmpl_id.product_variant_id

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    @api.model
    def _normalize_name(self, name):
        """Comparable form of a product name.

        The two catalogues were keyed separately, so the same item may differ by
        whitespace, by the full-width bracket or by the multiplication sign.
        """
        text = (name or '').strip().lower()
        for source, target in (('（', '('), ('）', ')'), ('×', 'x'),
                               ('＊', '*'), ('　', '')):
            text = text.replace(source, target)
        return ' '.join(text.split())

    @api.model
    def _find(self, source_product, target_company):
        """Mapping of ``source_product`` towards ``target_company``, if any."""
        if not source_product or source_product.company_id == target_company:
            return self.browse()
        return self.sudo().search([
            ('source_company_id', '=', source_product.company_id.id),
            ('target_company_id', '=', target_company.id),
            ('source_product_tmpl_id', '=', source_product.product_tmpl_id.id),
        ], limit=1)

    @api.model
    def _sn_resolve_product(self, product, target_company, agreement=False,
                            create=True, record=True):
        """Product of ``target_company`` standing for ``product``.

        Returns a tuple ``(product, mapping, mode)``:

        * ``direct``  the product already belongs to the target company (or is
          shared), it can be written as is;
        * ``mapped``  an explicit mapping exists;
        * ``code``    the target company holds a product with the same code and
          the same name, the mapping was recorded on the fly;
        * ``created`` the target company had no such product and one was
          created from the source one;
        * ``text``    nothing usable was found, the caller must copy the line as
          text.
        """
        if not product:
            return self.env['product.product'], self.browse(), RESOLUTION_TEXT
        if not target_company:
            return self.env['product.product'], self.browse(), RESOLUTION_TEXT
        if not product.company_id or product.company_id == target_company:
            return product, self.browse(), RESOLUTION_DIRECT

        mapping = self._find(product, target_company)
        if mapping:
            mapped = mapping._mapped_product()
            if mapped:
                return mapped, mapping, RESOLUTION_MAPPED
            return self.env['product.product'], mapping, RESOLUTION_TEXT

        source_company = product.company_id
        # Matching by code is safe on its own (code *and* name must agree), so
        # it also runs for the company level switches that work without an
        # agreement. Creating a product in the other company is a master data
        # change and stays opt-in through the agreement.
        auto_map = agreement.auto_map_by_code if agreement else True
        auto_create = agreement.auto_create_target_product if agreement else False

        if auto_map:
            match = self._match_by_code(product, target_company)
            if match:
                mapping = self._record(source_company, target_company, product,
                                       match, 'code', agreement) if record else self.browse()
                return match.product_variant_id, mapping, RESOLUTION_CODE

        if auto_create and create:
            created = self._create_target_product(product, target_company, agreement)
            if created:
                mapping = self._record(source_company, target_company, product,
                                       created, 'created', agreement) if record else self.browse()
                return created.product_variant_id, mapping, RESOLUTION_CREATED
        elif auto_create and not create:
            # Dry run: report that the product would be created.
            return self.env['product.product'], self.browse(), RESOLUTION_CREATABLE

        return self.env['product.product'], self.browse(), RESOLUTION_TEXT

    @api.model
    def _match_by_code(self, product, target_company):
        """Product of the target company with the same code and the same name.

        The two Kingdee accounts share 257 codes describing 252 *different*
        items, so a code alone is never enough: the name has to match as well,
        otherwise the buyer would silently receive the wrong article.
        """
        code = (product.default_code or '').strip()
        if not code:
            return self.env['product.template']
        candidates = self.env['product.template'].sudo().search([
            ('default_code', '=', code),
            ('company_id', 'in', (target_company.id, False)),
        ])
        wanted = self._normalize_name(product.name)
        matches = candidates.filtered(
            lambda candidate: self._normalize_name(candidate.name) == wanted)
        return matches[:1] if len(matches) == 1 else self.env['product.template']

    @api.model
    def _create_target_product(self, product, target_company, agreement):
        """Copy ``product`` into ``target_company``.

        The code is kept when it is free in the target company. When another
        article already owns it, the prefix of the agreement is prepended; with
        no prefix configured the product is not created at all, because a
        duplicated code would make the next resolution pick the wrong article.
        """
        code = (product.default_code or '').strip()
        Product = self.env['product.template'].sudo()
        taken = Product.search_count([
            ('default_code', '=', code), ('company_id', '=', target_company.id),
        ]) if code else 0
        if taken:
            prefix = (agreement.target_code_prefix or '').strip() if agreement else ''
            if not prefix:
                return Product.browse()
            code = '%s%s' % (prefix, code)
            if Product.search_count([
                    ('default_code', '=', code),
                    ('company_id', '=', target_company.id)]):
                return Product.browse()
        values = {
            'name': product.name,
            'default_code': code or False,
            'company_id': target_company.id,
            'uom_id': product.uom_id.id,
            'categ_id': self._target_category(product, target_company).id,
            'type': product.type,
            'is_storable': product.is_storable,
            'tracking': product.tracking,
            'purchase_ok': True,
            'sale_ok': True,
            'intercompany_generated': True,
        }
        if 'material_specification' in product._fields:
            values['material_specification'] = product.material_specification
        return self.env['product.template'].sudo().with_company(target_company).create(values)

    @api.model
    def _target_category(self, product, target_company):
        """Category of the target company matching the one of the source.

        Both trees were built from the Kingdee material groups, so the leaf
        names line up. When they do not, the first category of the target
        company is used; a company without any category gets a root of its own
        rather than failing the whole document.
        """
        Category = self.env['product.category'].sudo()
        scoped = 'company_id' in Category._fields
        domain = [('company_id', 'in', (target_company.id, False))] if scoped else []
        if product.categ_id:
            match = Category.search(domain + [('name', '=', product.categ_id.name)], limit=1)
            if match:
                return match
        fallback = Category.search(domain + [('parent_id', '=', False)], limit=1)
        if fallback:
            return fallback
        root = Category.search(domain, limit=1)
        if root:
            return root
        values = {'name': _('Inter-Company Products')}
        if scoped:
            values['company_id'] = target_company.id
        return Category.with_company(target_company).create(values)

    @api.model
    def _record(self, source_company, target_company, source_product, target_product,
                origin, agreement):
        """Remember the resolution, tolerating a concurrent insert."""
        values = {
            'source_company_id': source_company.id,
            'target_company_id': target_company.id,
            'source_product_tmpl_id': source_product.product_tmpl_id.id,
            'target_product_tmpl_id': target_product.id if target_product else False,
            'origin': origin,
            'agreement_id': agreement.id if agreement else False,
            'direction': agreement._direction_from(source_company) if agreement else False,
        }
        Map = self.sudo()
        try:
            with self.env.cr.savepoint():
                return Map.create(values)
        except Exception:  # another transaction recorded the same pair first
            _logger.info("Inter-company product map already created for %s -> %s",
                         source_product.display_name, target_company.display_name)
            return Map._find(source_product, target_company)
