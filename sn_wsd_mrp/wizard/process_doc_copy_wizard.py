from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProcessDocCopyWizard(models.TransientModel):
    """工艺文件跨订单复制：订单之间方案相近时，选源订单+目标订单，
    一次把源单的清单（工序+类型+编号）复制过去；目标单已有同组合
    清单的只追加缺的编号（与快速录入同一合并语义）。"""

    _name = 'production.process.doc.copy.wizard'
    _description = 'Process Document Copy'

    source_production_id = fields.Many2one(
        'mrp.production', required=True, string='Source Manufacturing Order')
    source_drawing_code = fields.Char(
        related='source_production_id.product_id.default_code',
        string='Drawing No.')
    target_production_id = fields.Many2one(
        'mrp.production', required=True, string='Target Manufacturing Order')
    target_drawing_code = fields.Char(
        related='target_production_id.product_id.default_code',
        string='Drawing No.')
    line_ids = fields.One2many(
        'production.process.doc.copy.line', 'wizard_id',
        string='Lists to Copy')

    @api.model
    def default_get(self, fields_list):
        # 列表上勾选了清单行再点复制：源订单按第一行的单预填
        defaults = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        docs = self.env['production.process.document'].browse(active_ids).exists()
        if docs:
            defaults['source_production_id'] = docs[:1].production_id.id
        return defaults

    @api.onchange('source_production_id')
    def _onchange_source_production_id(self):
        # 换源订单时重拉该单全部清单行（用户可删减）
        self.line_ids = [(5, 0, 0)] + [
            (0, 0, {'source_document_id': doc.id})
            for doc in self.source_production_id.x_process_document_ids
        ]

    @api.constrains('line_ids')
    def _check_has_lines(self):
        for wizard in self:
            if not wizard.line_ids:
                raise ValidationError(_('Add at least one list to copy.'))

    def action_apply(self):
        self.ensure_one()
        Document = self.env['production.process.document']
        created = appended = skipped = 0
        for line in self.line_ids:
            source = line.source_document_id
            _doc, was_created, line_appended, line_skipped = (
                Document._upsert_document_list(
                    self.target_production_id,
                    source.operation_id, source.type_id,
                    source.code_ids.mapped('code')))
            created += int(was_created)
            appended += line_appended
            skipped += line_skipped
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Process Documents Copied'),
                'message': _(
                    'Created %(created)s list(s), appended %(appended)s '
                    'number(s), skipped %(skipped)s already present.',
                    created=created, appended=appended, skipped=skipped),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class ProcessDocCopyLine(models.TransientModel):
    _name = 'production.process.doc.copy.line'
    _description = 'Process Document Copy Line'

    wizard_id = fields.Many2one(
        'production.process.doc.copy.wizard', required=True,
        ondelete='cascade')
    source_document_id = fields.Many2one(
        'production.process.document', required=True)
    operation_id = fields.Many2one(
        related='source_document_id.operation_id', string='Operation')
    type_id = fields.Many2one(
        related='source_document_id.type_id', string='Type')
    codes_display = fields.Char(
        related='source_document_id.codes_display', string='Codes Display')
