from odoo import models


class SerialBindingEip(models.Model):
    """Capture hook: a new nameplate-to-machine binding is one packing
    storage event -- the EIP 1090/2090 row is born here, inside the
    binding transaction."""
    _inherit = 'sn.wsd.serial.binding'

    def create(self, vals_list):
        records = super().create(vals_list)
        self.env['sn.wsd.eip.pack.record'].sudo()._eip_capture_from_bindings(
            records)
        return records
