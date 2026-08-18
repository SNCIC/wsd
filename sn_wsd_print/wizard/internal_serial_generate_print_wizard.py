from odoo import api, fields, models, _
from odoo.exceptions import UserError


class InternalSerialGeneratePrintWizard(models.TransientModel):
    _name = 'sn.wsd.internal.serial.generate.print.wizard'
    _description = 'Generate and Print Factory Serial Numbers'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        required=True,
        readonly=True,
    )
    product_id = fields.Many2one(
        related='mes_order_id.product_id',
        string='Product',
        readonly=True,
    )
    planned_qty = fields.Float(
        related='mes_order_id.planned_qty',
        string='Planned Quantity',
        readonly=True,
    )
    active_internal_serial_count = fields.Integer(
        compute='_compute_serial_counts',
        string='Active Internal Serial Count',
        readonly=True,
    )
    missing_internal_serial_count = fields.Integer(
        compute='_compute_serial_counts',
        string='Remaining Quantity to Generate',
        readonly=True,
    )
    quantity = fields.Integer(string='Generate Quantity', required=True, default=1)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if values.get('mes_order_id') and 'quantity' in fields_list and not values.get('quantity'):
            values['quantity'] = values.get('missing_internal_serial_count') or 1
        return values

    @api.depends('mes_order_id.internal_serial_ids.active', 'mes_order_id.planned_qty')
    def _compute_serial_counts(self):
        for wizard in self:
            active = wizard.mes_order_id.internal_serial_ids.filtered(
                lambda serial: serial.active and not serial.is_confirmed_scrapped()
            )
            wizard.active_internal_serial_count = len(active)
            wizard.missing_internal_serial_count = max(
                int(round(wizard.mes_order_id.planned_qty or 0)) - len(active), 0
            )

    @api.onchange('mes_order_id')
    def _onchange_mes_order_id(self):
        for wizard in self:
            wizard.quantity = wizard.missing_internal_serial_count or 1

    def action_confirm(self):
        self.ensure_one()
        if self.quantity <= 0:
            raise UserError(_('The generate quantity must be positive.'))
        if self.quantity > self.missing_internal_serial_count:
            raise UserError(_(
                'The generate quantity cannot exceed the remaining quantity %(remaining)s.'
            ) % {'remaining': self.missing_internal_serial_count})

        serials = self.mes_order_id.action_generate_missing_internal_serials(
            quantity=self.quantity,
        )
        action = self.env.ref('sn_wsd_print.action_report_internal_serial_label_zpl').report_action(
            serials,
            config=False,
        )
        action['close_on_report_download'] = True
        return action
