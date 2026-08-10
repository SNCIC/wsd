from odoo import fields, models


class SnMsdBakeWizard(models.TransientModel):
    _name = 'sn.msd.bake.wizard'
    _description = 'MSD Bake Wizard'

    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number', required=True)
    rule_id = fields.Many2one(related='lot_id.msd_rule_id', readonly=True)
    bake_temperature = fields.Float(related='rule_id.bake_temperature', readonly=True)
    bake_duration_min = fields.Integer(related='rule_id.bake_duration_min', readonly=True)
    bake_duration_max = fields.Integer(related='rule_id.bake_duration_max', readonly=True)
    bake_minutes = fields.Integer(string='Bake Minutes', required=True)
    oven_info = fields.Char(string='Oven Information')

    def action_start_bake(self):
        self.ensure_one()
        self.lot_id._msd_start_bake(self.bake_minutes, oven_info=self.oven_info)
        return {'type': 'ir.actions.act_window_close'}
