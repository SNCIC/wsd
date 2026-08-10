from odoo import fields, models, _


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    x_exception_record_ids = fields.One2many(
        'sn.wsd.exception.record',
        'workorder_id',
        string='Exception Records',
        readonly=True,
    )
    x_exception_record_count = fields.Integer(
        string='Exception Count',
        compute='_compute_x_exception_record_count',
    )

    def _compute_x_exception_record_count(self):
        for workorder in self:
            workorder.x_exception_record_count = len(workorder.x_exception_record_ids)

    def action_open_exception_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Exception Records'),
            'res_model': 'sn.wsd.exception.record',
            'view_mode': 'list,form',
            'domain': [('workorder_id', '=', self.id)],
            'context': {
                'default_workorder_id': self.id,
                'default_production_id': self.production_id.id,
                'default_workcenter_id': self.workcenter_id.id,
                'default_route_step_id': self.x_route_operation_id.id,
                'default_equipment_id': self.x_meter_equipment_id.id,
                'default_company_id': self.company_id.id,
            },
        }
