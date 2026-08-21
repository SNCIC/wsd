from odoo import fields, models


class SnConsumableLoadWizard(models.TransientModel):
    _name = 'sn.consumable.load.wizard'
    _description = 'Consumable Load Wizard'

    info_id = fields.Many2one(
        'sn.consumable.info',
        string='Consumable SN',
        required=True,
        check_company=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        required=True,
        check_company=True,
    )

    def action_confirm(self):
        self.ensure_one()
        self.info_id.action_load(self.mes_order_id)
        return {'type': 'ir.actions.act_window_close'}


class SnConsumableScrapWizard(models.TransientModel):
    _name = 'sn.consumable.scrap.wizard'
    _description = 'Consumable Scrap Wizard'

    info_id = fields.Many2one(
        'sn.consumable.info',
        string='Consumable SN',
        required=True,
        check_company=True,
    )
    reason = fields.Char(string='Scrap Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.info_id.action_scrap(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
