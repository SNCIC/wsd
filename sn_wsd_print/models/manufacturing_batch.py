from odoo import models, _


class SnManufacturingBatch(models.Model):
    _inherit = 'sn.wsd.manufacturing.batch'

    def action_open_generate_internal_serial_print_wizard(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'sn_wsd_print.action_sn_wsd_internal_serial_generate_print_wizard'
        )
        action['context'] = {
            'default_batch_id': self.id,
            'default_quantity': self.missing_internal_serial_count,
        }
        return action
