from odoo import api, fields, models, _


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    x_mes_travel_ids = fields.One2many(
        'sn.wsd.mes.sn.travel',
        'workorder_id',
        string='MES Travel Events',
        readonly=True,
    )
    x_mes_travel_count = fields.Integer(
        string='MES Travel Event Count',
        compute='_compute_x_mes_travel_count',
    )
    x_meter_test_result_ids = fields.One2many(
        'sn.wsd.mes.test.result',
        'workorder_id',
        string='MES Test Results',
        readonly=True,
    )

    @api.depends('x_mes_travel_ids')
    def _compute_x_mes_travel_count(self):
        grouped_counts = self.env['sn.wsd.mes.sn.travel']._read_group(
            [('workorder_id', 'in', self.ids)],
            groupby=['workorder_id'],
            aggregates=['__count'],
        ) if self.ids else []
        counts = {workorder.id: count for workorder, count in grouped_counts}
        for workorder in self:
            workorder.x_mes_travel_count = counts.get(workorder.id, 0)

    def action_open_mes_travel_events(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'sn_wsd_api.action_sn_wsd_mes_sn_travel'
        )
        action['name'] = _('MES Travel Events - %s', self.display_name)
        action['domain'] = [('workorder_id', '=', self.id)]
        action['context'] = {
            'default_workorder_id': self.id,
            'default_production_id': self.production_id.id,
            'create': False,
        }
        return action
