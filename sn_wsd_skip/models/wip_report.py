from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _skip_get_effective_workorders(self, workorders):
        self.ensure_one()
        skipped_workorders = self.env['sn.wsd.skip.request.line'].get_approved_skip_workorders(self, workorders)
        return workorders - skipped_workorders

    def _build_wip_snapshot_line_values(self, workorders):
        self.ensure_one()
        return super()._build_wip_snapshot_line_values(self._skip_get_effective_workorders(workorders))


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    x_skip_effective = fields.Boolean(string='Skip Effective', compute='_compute_x_skip_effective')

    def _compute_x_skip_effective(self):
        line_model = self.env['sn.wsd.skip.request.line']
        for workorder in self:
            workorder.x_skip_effective = bool(line_model.search_count([
                ('workorder_id', '=', workorder.id),
                ('request_id.state', '=', 'approved'),
            ]))
