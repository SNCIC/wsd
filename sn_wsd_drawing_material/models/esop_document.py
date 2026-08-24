from odoo import _, api, fields, models
from odoo.addons.sn_wsd_mrp.models.constants import (
    BOARD_SIDE_SELECTION,
    SIDE_SELECTION,
)

DOC_TYPE_SELECTION = [
    ('instruction', 'Work Instruction'),
    ('drawing', 'Drawing'),
    ('inspection', 'Inspection Standard'),
    ('other', 'Other'),
]

DOC_STATE_SELECTION = [
    ('active', 'In Use'),
    ('archived', 'Archived'),
]


def esop_bus_channel(company_id):
    """Per-company refresh channel for the ESOP fullscreen page."""
    return 'sn_wsd_drawing_material.esop_%s' % company_id


class SnWsdEsopDocument(models.Model):
    """One ESOP (electronic work instruction) file in active use.

    Dimension: (company, drawing, operation, side, doc_type) keeps a
    single active document. Re-uploading for the same dimension archives
    the previous record automatically, so version history stays
    queryable without an approval flow.
    """
    _name = 'sn.wsd.esop.document'
    _description = 'ESOP Document'
    _inherit = ['mail.thread']
    _order = 'x_drawing_no, operation_id, x_side, doc_type, id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
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
    doc_type = fields.Selection(
        DOC_TYPE_SELECTION,
        string='Document Type',
        required=True,
        index=True,
        tracking=True,
    )
    name = fields.Char(string='Document Title', required=True, tracking=True)
    file = fields.Binary(string='File', attachment=True, required=True)
    file_name = fields.Char(string='File Name')
    version = fields.Char(
        string='Version', default='V1', required=True, copy=False,
        tracking=True)
    state = fields.Selection(
        DOC_STATE_SELECTION,
        string='Status',
        default='active',
        required=True,
        index=True,
        copy=False,
        tracking=True,
    )
    archived_date = fields.Datetime(string='Archived On', readonly=True, copy=False)
    archived_uid = fields.Many2one(
        'res.users', string='Archived By', readonly=True, copy=False)
    ack_ids = fields.One2many(
        'sn.wsd.esop.acknowledge', 'document_id', string='Acknowledgements')

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

    # NULL when archived: PG unique ignores NULLs, so only active rows
    # occupy the dimension slot and history never collides.
    active_uniq_key = fields.Char(
        compute='_compute_active_uniq_key',
        store=True,
        index=True,
    )

    _esop_active_uniq = models.Constraint(
        'unique(active_uniq_key)',
        'This drawing already has an active document of this type for '
        'this operation and side.',
    )

    @api.depends(
        'company_id', 'x_drawing_no', 'operation_id', 'x_side', 'doc_type',
        'state')
    def _compute_active_uniq_key(self):
        for document in self:
            if document.state == 'active' and document.x_drawing_no \
                    and document.operation_id and document.x_side \
                    and document.doc_type:
                document.active_uniq_key = '|'.join([
                    str(document.company_id.id),
                    document.x_drawing_no,
                    str(document.operation_id.id),
                    document.x_side,
                    document.doc_type,
                ])
            else:
                document.active_uniq_key = False

    @api.depends('x_drawing_no')
    def _compute_product_info(self):
        """按图号带出产品信息（与 sn.wsd.process.route.drawing 同口径：
        图号 = product.product.default_code，多匹配取第一条，无匹配留空）。"""
        ProductProduct = self.env['product.product']
        for document in self:
            product = ProductProduct
            if document.x_drawing_no:
                product = ProductProduct.search(
                    [('default_code', '=', document.x_drawing_no)],
                    limit=1,
                )
            document.product_id = product
            document.product_name = product.product_tmpl_id.name or False
            document.product_board_side = product.x_board_side or False
            document.product_specification = \
                product.material_specification or False

    # 非存储 compute 不随 onchange 自动回传，显式挂 onchange 让新建时
    # 输完图号（失焦）即可看到产品信息，而不是保存后才出现。
    @api.onchange('x_drawing_no')
    def _onchange_drawing_no(self):
        self._compute_product_info()

    @api.depends(
        'x_drawing_no', 'operation_id.display_name', 'x_side', 'doc_type')
    def _compute_display_name(self):
        # 面别标签取 fields_get 的翻译结果，避免中文界面出现 "Top (T)"。
        side_labels = dict(self.fields_get(['x_side'])['x_side']['selection'])
        type_labels = dict(
            self.fields_get(['doc_type'])['doc_type']['selection'])
        for document in self:
            parts = [
                document.x_drawing_no or '',
                document.operation_id.display_name or '',
                side_labels.get(document.x_side or '', ''),
                type_labels.get(document.doc_type or '', ''),
            ]
            document.display_name = ' / '.join(part for part in parts if part)

    # ------------------------------------------------------------------
    # reversion: creating a document for an occupied dimension archives
    # the previous one and takes over the next version number
    # ------------------------------------------------------------------

    def _esop_dimension_domain(self, company_id, drawing, operation_id,
                               side, doc_type):
        return [
            ('company_id', '=', company_id),
            ('x_drawing_no', '=', drawing),
            ('operation_id', '=', operation_id),
            ('x_side', '=', side),
            ('doc_type', '=', doc_type),
        ]

    def _esop_next_version(self, company_id, drawing, operation_id, side,
                           doc_type):
        previous = self.search(self._esop_dimension_domain(
            company_id, drawing, operation_id, side, doc_type))
        highest = 0
        for document in previous:
            try:
                highest = max(highest, int(document.version.lstrip('Vv')))
            except ValueError:
                continue
        return 'V%d' % (highest + 1)

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            if vals.get('state', 'active') != 'active':
                continue
            company_id = vals.get('company_id') or self.env.company.id
            dimension = (
                company_id,
                vals.get('x_drawing_no'),
                vals.get('operation_id'),
                vals.get('x_side'),
                vals.get('doc_type'),
            )
            previous = self.search(
                self._esop_dimension_domain(*dimension)
                + [('state', '=', 'active')])
            if previous:
                previous.write({
                    'state': 'archived',
                    'archived_date': now,
                    'archived_uid': self.env.uid,
                })
                # 归档必须先落库：新记录的 INSERT 会立刻占用同一个
                # active_uniq_key，而同一事务里 write/create 的 flush
                # 顺序并不保证 UPDATE 先执行，不 flush 会撞唯一约束。
                previous.flush_recordset()
            # 版本一律服务端接序：表单会把字段默认值 V1 一起提交，
            # 若尊重传入值，换版记录的版本号永远停在 V1。
            vals['version'] = self._esop_next_version(*dimension)
        documents = super().create(vals_list)
        documents._esop_bus_notify()
        return documents

    def write(self, vals):
        result = super().write(vals)
        if vals.keys() & {'state', 'file', 'version'}:
            self._esop_bus_notify()
        return result

    def _esop_bus_notify(self):
        for company in self.mapped('company_id'):
            self.env['bus.bus']._sendone(
                esop_bus_channel(company.id), 'esop_refresh', True)

    def action_download(self):
        """Let the browser download the attached file."""
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content?model=sn.wsd.esop.document'
                   f'&id={self.id}&field=file&filename_field=file_name'
                   f'&download=true',
            'target': 'self',
        }

    # ------------------------------------------------------------------
    # ESOP fullscreen page payload / acknowledgement
    # ------------------------------------------------------------------

    @api.model
    def esop_file_url(self, document_id):
        return '/web/content?model=sn.wsd.esop.document&id=%s' \
               '&field=file&filename_field=file_name' % document_id

    def _esop_unacked_map(self, employee):
        """document id -> True when the current version is not yet
        acknowledged by the given employee."""
        if not employee:
            return {}
        Acknowledge = self.env['sn.wsd.esop.acknowledge']
        acked = Acknowledge.search([
            ('employee_id', '=', employee.id),
            ('document_id', 'in', self.ids),
        ])
        acked_keys = {(ack.document_id.id, ack.version) for ack in acked}
        return {
            document.id: (document.id, document.version) not in acked_keys
            for document in self
        }

    @api.model
    def esop_screen_data(self, search=''):
        """Everything the ESOP fullscreen page needs for one render."""
        company = self.env.company
        employee = self.env.user.employee_id
        search = (search or '').strip()
        documents = self.search([
            ('company_id', '=', company.id),
            ('state', '=', 'active'),
            ('x_drawing_no', '=ilike', '%s%%' % search),
        ]) if search else self.search([
            ('company_id', '=', company.id),
            ('state', '=', 'active'),
        ])
        unacked = documents._esop_unacked_map(employee)
        payload = {
            'company_id': company.id,
            'search': search,
            'can_ack': bool(employee),
            'docs': [{
                'id': document.id,
                'drawing': document.x_drawing_no,
                'operation': document.operation_id.display_name or '',
                'side': document.x_side,
                'doc_type': document.doc_type,
                'name': document.name,
                'version': document.version,
                'file_name': document.file_name or '',
                'url': self.esop_file_url(document.id),
                'unacked': unacked.get(document.id, False),
            } for document in documents],
        }
        payload['cards'] = self._esop_landing_cards(search, unacked)
        return payload

    def _esop_landing_cards(self, search, unacked_map):
        """One card per drawing of the company's in-production MES orders."""
        if search:
            return []
        orders = self.env['sn.wsd.mes.order'].search([
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'in_progress'),
        ])
        cards = {}
        for order in orders:
            drawing = order.product_id.default_code
            if not drawing:
                continue
            card = cards.setdefault(drawing, {
                'drawing': drawing,
                'product_name': order.product_id.product_tmpl_id.name or '',
                'workshops': [],
                'unacked': False,
            })
            workshop = order.x_workshop_id.name
            if workshop and workshop not in card['workshops']:
                card['workshops'].append(workshop)
        documents = self.search([
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'active'),
            ('x_drawing_no', 'in', list(cards)),
        ])
        for document in documents:
            if document.id in unacked_map and unacked_map[document.id]:
                cards[document.x_drawing_no]['unacked'] = True
        return [cards[drawing] for drawing in sorted(cards)]

    def esop_acknowledge(self):
        """Record a read-acknowledgement of the current version for the
        logged-in user's employee (search-then-create: acknowledging an
        already acknowledged version is a no-op)."""
        employee = self.env.user.employee_id
        if not employee:
            return {'acknowledged': False}
        Acknowledge = self.env['sn.wsd.esop.acknowledge']
        existing = Acknowledge.search([
            ('employee_id', '=', employee.id),
            ('document_id', 'in', self.ids),
        ])
        done_keys = {(ack.document_id.id, ack.version) for ack in existing}
        for document in self:
            if (document.id, document.version) in done_keys:
                continue
            Acknowledge.create({
                'employee_id': employee.id,
                'document_id': document.id,
                'version': document.version,
            })
        return {'acknowledged': True}
