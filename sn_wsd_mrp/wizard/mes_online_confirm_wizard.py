from odoo import _, api, fields, models


class MesOnlineConfirmWizard(models.TransientModel):
    """顶替上线确认（上线按钮的占用确认弹窗）。

    产线已有在线制令单时，action_online 返回本向导——提示里指明占用者，
    确认后占用单自动下线、本单上线；取消则不动。"""

    _name = 'sn.wsd.mes.online.confirm'
    _description = 'Go Online Replace Confirmation'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', required=True, ondelete='cascade')
    occupying_ids = fields.Many2many(
        'sn.wsd.mes.order', string='Occupying Orders')
    message = fields.Text(compute='_compute_message')

    @api.depends('mes_order_id', 'occupying_ids')
    def _compute_message(self):
        for wizard in self:
            others = ', '.join(wizard.occupying_ids.mapped('name')) or '-'
            line = wizard.mes_order_id.production_line_id.display_name or '-'
            wizard.message = _(
                'Production line %(line)s currently runs online MES order(s) '
                '%(others)s. Confirm to replace: %(others)s is taken offline '
                'automatically (boards already in flow keep moving) and '
                '%(name)s goes online (SNs may then be fed in and the '
                'management mode is locked).',
                line=line, others=others, name=wizard.mes_order_id.name)

    def action_confirm_replace(self):
        self.ensure_one()
        self.mes_order_id._apply_online(self.occupying_ids)
        return {'type': 'ir.actions.act_window_close'}
