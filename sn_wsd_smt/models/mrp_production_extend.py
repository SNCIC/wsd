from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MrpProductionExtend(models.Model):
    _name = 'mrp.production'
    _inherit = ['mrp.production']

    x_smt_pcb_panel_count = fields.Integer(
        string='PCB Panel Count',
        compute='_compute_smt_pcb_panel_count',
        store=False,
    )
    # One2many reverse link to panel records through production_id.
    x_smt_pcb_panel_ids = fields.One2many(
        'sn.smt.pcb.panel',
        'production_id',
        string='SMT PCB Panels',
    )

    @api.depends('x_smt_pcb_panel_ids')
    def _compute_smt_pcb_panel_count(self):
        """Compute the related SMT PCB panel record count."""
        for production in self:
            production.x_smt_pcb_panel_count = len(production.x_smt_pcb_panel_ids)

    def action_open_smt_pcb_panels(self):
        """Open the SMT PCB panel list."""
        self.ensure_one()
        return {
            'name': 'SMT PCB Panels',
            'type': 'ir.actions.act_window',
            'res_model': 'sn.smt.pcb.panel',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'create': False},
        }

    def _get_smt_effective_pcb_board_qty(self):
        self.ensure_one()
        return self.env['sn.smt.pcb.board'].search_count([
            ('panel_id.production_id', '=', self.id),
            '|',
            ('state', '=', False),
            ('state', 'in', ['active', 'scrapped']),
        ])

    def _get_smt_pcb_board_capacity_values(self, requested_qty=0):
        self.ensure_one()
        planned_qty = int(self.product_uom_id.round(self.product_qty))
        existing_qty = self._get_smt_effective_pcb_board_qty()
        allowed_extra_qty = 0
        available_qty = max(planned_qty + allowed_extra_qty - existing_qty, 0)
        return {
            'planned_qty': planned_qty,
            'existing_qty': existing_qty,
            'requested_qty': int(requested_qty or 0),
            'allowed_extra_qty': allowed_extra_qty,
            'available_qty': available_qty,
        }

    def _check_smt_pcb_board_capacity(self, requested_qty):
        self.ensure_one()
        values = self._get_smt_pcb_board_capacity_values(requested_qty)
        if values['requested_qty'] > values['available_qty']:
            raise ValidationError(_(
                'SMT PCB board quantity exceeds manufacturing order planned quantity. '
                'Planned: %(planned_qty)s, existing effective: %(existing_qty)s, requested: %(requested_qty)s, available: %(available_qty)s.'
            ) % values)
        return values
