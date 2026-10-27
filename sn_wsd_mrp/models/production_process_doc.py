from odoo import api, fields, models


class ProductionProcessDocType(models.Model):
    """Lightweight type list for craft documents maintained on the MO
    (default four, extensible without code)."""
    _name = 'production.process.doc.type'
    _description = 'Production Process Document Type'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True,
                       help='Stable key the device API checks against.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda self: self.env.company)

    _code_uniq = models.Constraint(
        'unique(company_id, code)',
        'The process document type code must be unique per company.')


class ProductionProcessDoc(models.Model):
    """Craft documents maintained per MO + operation: a type and any number
    of document numbers (codes). The device API validates uploaded numbers
    against these lists."""
    _name = 'production.process.document'
    _description = 'Production Process Document'
    _order = 'production_id, id'

    production_id = fields.Many2one(
        'mrp.production', required=True, index=True, ondelete='cascade')
    drawing_code = fields.Char(
        related='production_id.product_id.default_code',
        string='Drawing No.', store=True, index=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
        related='production_id.company_id', store=True, readonly=False)
    operation_id = fields.Many2one(
        'sn.wsd.operation', string='Operation', index=True,
        check_company=True)
    route_operation_code = fields.Char(
        required=True, index=True,
        help='Operation code of the MES-order route operation this list '
             'applies to. Auto-filled from the operation picker; the '
             'device API matches uploaded numbers against it.')
    type_id = fields.Many2one(
        'production.process.doc.type', required=True, index=True,
        domain="[('company_id', 'in', [company_id, False])]")
    code_ids = fields.One2many(
        'production.process.document.code', 'document_id', string='Codes')
    codes_display = fields.Char(compute='_compute_codes_display')
    note = fields.Text()

    @api.onchange('operation_id')
    def _onchange_operation_id(self):
        # 选择工序后自动落码：API 匹配键 = 工序.code（无 code 用 name），
        # 与 _check_process_documents 的匹配口径一致。
        if self.operation_id:
            self.route_operation_code = (
                self.operation_id.code or self.operation_id.name)

    @api.model
    def _upsert_document_list(self, production, operation, doc_type, codes):
        """查找或创建 制造订单+工序+类型 的清单并追加缺失编号（不删不改
        既有编号）。返回 (清单, 追加数, 跳过数)；快速录入与跨订单复制共用。"""
        self = self.with_company(production.company_id)
        op_code = operation.code or operation.name
        document = self.search([
            ('production_id', '=', production.id),
            ('route_operation_code', '=', op_code),
            ('type_id', '=', doc_type.id),
        ], limit=1)
        created = False
        if not document:
            document = self.create({
                'production_id': production.id,
                'operation_id': operation.id,
                'route_operation_code': op_code,
                'type_id': doc_type.id,
            })
            created = True
        existing = set(document.code_ids.mapped('code'))
        appended = skipped = 0
        for code in codes:
            if code in existing:
                skipped += 1
                continue
            self.env['production.process.document.code'].create({
                'document_id': document.id, 'code': code})
            existing.add(code)
            appended += 1
        return document, created, appended, skipped

    @api.depends('code_ids.code')
    def _compute_codes_display(self):
        for doc in self:
            doc.codes_display = ', '.join(doc.code_ids.mapped('code'))

    _op_type_uniq = models.Constraint(
        'unique(production_id, route_operation_code, type_id)',
        'One document list per operation and type on a manufacturing order.')


class ProductionProcessDocCode(models.Model):
    _name = 'production.process.document.code'
    _description = 'Production Process Document Number'

    document_id = fields.Many2one(
        'production.process.document', required=True, ondelete='cascade')
    code = fields.Char(required=True)
    company_id = fields.Many2one(
        related='document_id.company_id', store=True)

    _code_uniq = models.Constraint(
        'unique(document_id, code)',
        'The document number must be unique in its list.')
