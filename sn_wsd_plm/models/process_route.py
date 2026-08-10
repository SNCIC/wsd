from odoo import fields, models, _
from odoo.exceptions import UserError


class SnWsdProcessRoute(models.Model):
    _inherit = 'sn.wsd.process.route'

    x_revision_count = fields.Integer(
        string='Revision Count',
        compute='_compute_x_revision_count',
    )

    def _compute_display_name(self):
        super()._compute_display_name()
        if not self.env.context.get('sn_wsd_revision_display'):
            return
        for route in self:
            route.display_name = route.version or route.x_revision or route.code or str(route.id)

    def _compute_x_revision_count(self):
        for route in self:
            route.x_revision_count = self.with_context(active_test=False).search_count(
                route._get_revision_family_domain()
            )

    def action_compare_revisions(self):
        self.ensure_one()
        available_routes = self.with_context(active_test=False).search(
            self._get_revision_family_domain(),
            order='create_date desc, id desc',
        )
        base_route = self.x_previous_route_id
        if not base_route:
            base_route = (available_routes - self)[:1]
        if not base_route:
            raise UserError(_('No other route revision is available for comparison.'))
        wizard = self.env['sn.wsd.bom.version.compare.wizard'].create({
            'comparison_mode': 'route',
            'base_route_id': base_route.id,
            'target_route_id': self.id,
        })
        wizard._rebuild_comparison()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Process Route Version Comparison'),
            'res_model': 'sn.wsd.bom.version.compare.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }
