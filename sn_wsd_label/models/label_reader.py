from odoo import models


class SnLabelReader(models.AbstractModel):
    """Compatibility delegate: the generic reader now lives in
    sn_wsd_field (sn.field.reader); the label center keeps its historical
    model name so existing calls and translations keep working."""

    _name = 'sn.label.reader'
    _inherit = 'sn.field.reader'
    _description = 'Label Field Reader'
