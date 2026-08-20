from odoo import api, fields, models, _


class MesOrder(models.Model):
    _inherit = 'sn.wsd.mes.order'

    can_generate_internal_serials = fields.Boolean(
        string='Can Generate Internal Serials',
        compute='_compute_can_generate_internal_serials',
    )

    @api.depends('planned_qty', 'internal_serial_ids.active', 'internal_serial_ids.final_result')
    def _compute_can_generate_internal_serials(self):
        for order in self:
            active_serials = order.internal_serial_ids.filtered(
                lambda serial: serial.active and not serial.is_confirmed_scrapped()
            )
            order.can_generate_internal_serials = (
                order.state not in ('done', 'cancelled')
                and len(active_serials) < int(round(order.planned_qty or 0))
            )

    def action_open_generate_print_internal_serials(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate and Print Factory Serial Numbers'),
            'res_model': 'sn.wsd.internal.serial.generate.print.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref(
                'sn_wsd_print.view_sn_wsd_internal_serial_generate_print_wizard_form'
            ).id,
            'target': 'new',
            'context': {
                'default_mes_order_id': self.id,
            },
        }
