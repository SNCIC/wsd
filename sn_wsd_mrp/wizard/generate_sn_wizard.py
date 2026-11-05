from odoo import fields, models


class GenerateSnWizard(models.TransientModel):
    _name = 'sn.wsd.generate.sn.wizard'
    _description = 'Generate SNs for a MES Order'

    mes_order_id = fields.Many2one('sn.wsd.mes.order', required=True)
    quantity = fields.Integer(default=1, required=True)

    def action_generate(self):
        self.ensure_one()
        return self.mes_order_id.action_generate_sns(self.quantity)
