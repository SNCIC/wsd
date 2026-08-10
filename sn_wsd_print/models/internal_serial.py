from odoo import fields, models


class InternalSerial(models.Model):
    _inherit = 'sn.wsd.internal.serial'

    label_print_count = fields.Integer(string='Label Print Count', default=0, copy=False, readonly=True)
