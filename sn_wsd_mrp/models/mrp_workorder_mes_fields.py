from odoo import api, fields, models


class MrpWorkorderMesFields(models.Model):
    _inherit = 'mrp.workorder'

    x_mes_workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='MES Work Center',
        compute='_compute_x_mes_workcenter_id',
        store=True,
        readonly=False,
    )
    x_mes_execution_note = fields.Char(string='MES Execution Note', copy=False)

    @api.depends('x_meter_workcenter_id', 'workcenter_id', 'x_meter_production_line_id')
    def _compute_x_mes_workcenter_id(self):
        workcenter_model = self.env['mrp.workcenter']
        for workorder in self:
            if workorder.x_mes_workcenter_id and workorder.x_mes_workcenter_id == workorder.workcenter_id:
                if not workorder.x_meter_workcenter_id or workorder.x_meter_workcenter_id != workorder.x_mes_workcenter_id:
                    workorder.x_meter_workcenter_id = workorder.x_mes_workcenter_id
                continue
            if workorder.x_meter_workcenter_id:
                workorder.x_mes_workcenter_id = workorder.x_meter_workcenter_id
                continue
            workorder.x_mes_workcenter_id = workcenter_model.search([('id', '=', workorder.workcenter_id.id)], limit=1)
