from odoo import api, fields, models, _


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    x_skip_request_line_ids = fields.One2many(
        'sn.wsd.skip.request.line',
        'workorder_id',
        string='Skip Request Lines',
        readonly=True,
    )
    x_skip_request_count = fields.Integer(string='Skip Request Count', compute='_compute_x_skip_request_count')

    def _compute_x_skip_request_count(self):
        for workorder in self:
            workorder.x_skip_request_count = len(workorder.x_skip_request_line_ids)

    @api.depends('blocked_by_workorder_ids.qty_produced', 'blocked_by_workorder_ids.state')
    def _compute_qty_ready(self):
        super()._compute_qty_ready()
        line_model = self.env['sn.wsd.skip.request.line']
        for workorder in self:
            if workorder.state in ('cancel', 'done') or not workorder.blocked_by_workorder_ids:
                continue
            skipped_blockers = line_model.get_approved_skip_workorders(
                workorder.production_id,
                workorder.blocked_by_workorder_ids,
            )
            if not skipped_blockers:
                continue
            effective_blockers = workorder.blocked_by_workorder_ids - skipped_blockers
            if not effective_blockers or all(blocker.state == 'cancel' for blocker in effective_blockers):
                workorder.qty_ready = workorder.qty_remaining
                continue
            workorder_qty_ready = workorder.qty_remaining + workorder.qty_produced
            for blocker in effective_blockers:
                if blocker.state != 'cancel':
                    workorder_qty_ready = min(
                        workorder_qty_ready,
                        blocker.qty_produced + blocker.qty_reported_from_previous_wo,
                    )
            workorder.qty_ready = workorder_qty_ready - workorder.qty_produced - workorder.qty_reported_from_previous_wo

    def action_open_skip_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Skip Requests'),
            'res_model': 'sn.wsd.skip.request',
            'view_mode': 'list,form',
            'domain': [('line_ids.workorder_id', '=', self.id)],
            'context': {
                'default_production_id': self.production_id.id,
                'default_company_id': self.company_id.id,
            },
        }
