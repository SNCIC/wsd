import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# 编号输入分隔符：中英文逗号/分号、空白
CODE_SEPARATOR_RE = re.compile(r'[\s,;，；]+')


class ProcessDocQuickEntryWizard(models.TransientModel):
    """工艺文件快速录入：选一次 MO，一屏录完该单全部
    工序+类型+编号；保存时同工序同类型自动并成一张清单
    （已有的只追加缺的编号，不删不改既有数据）。"""

    _name = 'production.process.doc.quick.entry.wizard'
    _description = 'Process Document Quick Entry'

    production_id = fields.Many2one(
        'mrp.production', required=True, string='Manufacturing Order')
    drawing_code = fields.Char(
        related='production_id.product_id.default_code', string='Drawing No.')
    company_id = fields.Many2one(
        related='production_id.company_id', string='Company')
    line_ids = fields.One2many(
        'production.process.doc.quick.entry.line', 'wizard_id',
        string='Lines')

    @api.constrains('line_ids')
    def _check_has_lines(self):
        for wizard in self:
            if not wizard.line_ids:
                raise ValidationError(_('Add at least one line.'))

    def action_apply(self):
        self.ensure_one()
        # 同工序+类型的行自动并成一张清单（编号合并去重）
        grouped = {}
        for line in self.line_ids:
            codes = CODE_SEPARATOR_RE.split(line.codes_text or '')
            grouped.setdefault((line.operation_id, line.type_id), [])
            grouped[(line.operation_id, line.type_id)] += [
                code for code in codes if code
                and code not in grouped[(line.operation_id, line.type_id)]]
        Document = self.env['production.process.document']
        created = appended = skipped = 0
        for (operation, doc_type), codes in grouped.items():
            _doc, was_created, line_appended, line_skipped = (
                Document._upsert_document_list(
                    self.production_id, operation, doc_type, codes))
            created += int(was_created)
            appended += line_appended
            skipped += line_skipped
        return self._notify_applied(created, appended, skipped)

    def _notify_applied(self, created, appended, skipped):
        """右上角结果提示（与领料向导同款），随后关闭向导。"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Process Documents Saved'),
                'message': _(
                    'Created %(created)s list(s), appended %(appended)s '
                    'number(s), skipped %(skipped)s already present.',
                    created=created, appended=appended, skipped=skipped),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class ProcessDocQuickEntryLine(models.TransientModel):
    _name = 'production.process.doc.quick.entry.line'
    _description = 'Process Document Quick Entry Line'

    wizard_id = fields.Many2one(
        'production.process.doc.quick.entry.wizard', required=True,
        ondelete='cascade')
    operation_id = fields.Many2one('sn.wsd.operation', required=True)
    type_id = fields.Many2one(
        'production.process.doc.type', required=True, string='Type',
        domain="[('company_id', 'in', [company_id, False])]")
    codes_text = fields.Text(
        required=True, string='Numbers',
        help='One or more document numbers separated by commas or line '
             'breaks. They become one row each on the list.')
    company_id = fields.Many2one(related='wizard_id.company_id')
