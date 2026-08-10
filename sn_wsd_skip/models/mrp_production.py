from odoo import fields, models, _


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_skip_request_ids = fields.One2many(
        'sn.wsd.skip.request',
        'production_id',
        string='Skip Requests',
        readonly=True,
    )
    x_skip_request_count = fields.Integer(string='Skip Request Count', compute='_compute_x_skip_request_count')

    def _compute_x_skip_request_count(self):
        for production in self:
            production.x_skip_request_count = len(production.x_skip_request_ids)

    def action_open_skip_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Skip Requests'),
            'res_model': 'sn.wsd.skip.request',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {
                'default_production_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }
