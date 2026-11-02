from odoo import fields, models


class AgingDataRecord(models.Model):
    """One temperature point pushed by an aging-room device.

    Written by the login-free endpoint POST /api/device/aging (one row per
    packet: device_sn + collect_time + temperature). No product SN is
    involved -- the room temperature is an environment time series keyed
    by device; EIP collection (sn_wsd_eip) joins it on device + the
    pass enter/leave time window.
    """
    _name = 'sn.wsd.device.aging.record'
    _description = 'Aging Room Temperature Record'
    _order = 'collect_time desc, id desc'
    _rec_name = 'device_sn'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    device_sn = fields.Char(string='Device SN', required=True, index=True)
    temperature = fields.Float(string='Temperature', digits=(10, 1))
    collect_time = fields.Datetime(
        string='Collection Time',
        required=True,
        index=True,
        help='Timestamp reported by the device (stored as UTC).')
