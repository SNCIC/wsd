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


