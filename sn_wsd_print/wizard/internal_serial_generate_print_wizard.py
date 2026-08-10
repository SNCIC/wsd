from odoo import api, fields, models, _
from odoo.exceptions import UserError


class InternalSerialGeneratePrintWizard(models.TransientModel):
    _name = 'sn.wsd.internal.serial.generate.print.wizard'
    _description = 'Generate and Print Factory Serial Numbers'

    batch_id = fields.Many2one(
        'sn.wsd.manufacturing.batch',
        string='Manufacturing Batch',
        required=True,
        readonly=True,
    )
    product_id = fields.Many2one(
        related='batch_id.product_id',
        string='Product',
        readonly=True,
    )
    planned_qty = fields.Float(
        related='batch_id.planned_qty',
        string='Planned Quantity',
        readonly=True,
    )
    active_internal_serial_count = fields.Integer(
        related='batch_id.active_internal_serial_count',
        string='Active Internal Serial Count',
        readonly=True,
    )
    missing_internal_serial_count = fields.Integer(
        related='batch_id.missing_internal_serial_count',
        string='Remaining Quantity to Generate',
        readonly=True,
    )
    quantity = fields.Integer(string='Generate Quantity', required=True, default=1)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if values.get('batch_id') and 'quantity' in fields_list and not values.get('quantity'):
            batch = self.env['sn.wsd.manufacturing.batch'].browse(values['batch_id']).exists()
            values['quantity'] = batch.missing_internal_serial_count or 1
        return values

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
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

        serials = self.batch_id._generate_internal_serials(quantity=self.quantity)
        self.batch_id._post_internal_serial_generation_message(serials)
        action = self.env.ref('sn_wsd_print.action_report_internal_serial_label_zpl').report_action(
            serials,
            config=False,
        )
        action['close_on_report_download'] = True
        return action
