from odoo import fields, models


class DeviceDocType(models.Model):
    """Device document type dictionary.

    Business users maintain the list themselves (Configuration menu);
    documents pick a type from it via a Many2one dropdown.
    """
    _name = 'sn.wsd.device.doc.type'
    _description = 'Device Document Type'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    note = fields.Text(string='Notes')
