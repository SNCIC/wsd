from odoo import fields, models


class EquipmentDocument(models.Model):
    """A document archived under an equipment ledger record."""
    _name = 'sn.wsd.device.equipment.document'
    _description = 'Equipment Document'
    _order = 'id desc'

    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment',
        required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(
        related='equipment_id.company_id', store=True,
        string='Company', index=True)
    name = fields.Char(string='Document Name', required=True)
    doc_type_id = fields.Many2one(
        'sn.wsd.device.doc.type', string='Document Type', index=True)
    file = fields.Binary(string='File', attachment=True)
    file_name = fields.Char(string='File Name')
    note = fields.Text(string='Notes')
    archived_by = fields.Many2one(
        'res.users', string='Archived By',
        related='create_uid', readonly=True, store=True)
    archived_at = fields.Datetime(
        string='Archived At', related='create_date', readonly=True, store=True)

    def action_download(self):
        """Let the browser download the attached file."""
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model=sn.wsd.device.equipment.document'
                   f'&id={self.id}&field=file&filename_field=file_name'
                   f'&download=true',
            'target': 'self',
        }
