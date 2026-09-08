from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SnCodeRulePreview(models.TransientModel):
    """Render a rule against one existing record to preview its code —
    the configuration-time feedback loop (task 1.5)."""

    _name = 'sn.code.rule.preview'
    _description = 'Coding Rule Preview'

    rule_id = fields.Many2one(
        'sn.code.rule', required=True, ondelete='cascade')
    res_id = fields.Integer(
        string='Record', required=True,
        help='Id of an existing document record to render against.')
    result = fields.Char(readonly=True)
    error = fields.Char(readonly=True)

    def action_render(self):
        self.ensure_one()
        record = self.env[self.rule_id.model_id.model].browse(self.res_id)
        if not record.exists():
            raise UserError(_(
                'Record %s of model %s does not exist.',
                self.res_id, self.rule_id.model_id.model))
        try:
            self.result = self.rule_id.render(record)
            self.error = False
        except (ValidationError, UserError) as exc:
            self.result = False
            self.error = str(exc)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
