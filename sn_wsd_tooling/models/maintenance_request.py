from odoo import fields, models


class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    x_tooling_id = fields.Many2one('sn.tooling', string='Tooling', compute='_compute_x_tooling_id', store=True)

    def _compute_x_tooling_id(self):
        mapping = {
            tooling.maintenance_equipment_id.id: tooling.id
            for tooling in self.env['sn.tooling'].search([
                ('maintenance_equipment_id', 'in', self.mapped('equipment_id').ids),
            ])
        }
        for request in self:
            request.x_tooling_id = mapping.get(request.equipment_id.id)
