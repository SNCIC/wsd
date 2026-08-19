from odoo import fields, models


class WaveSolderingRecord(models.Model):
    """One data packet pushed by a wave soldering device."""
    _name = 'sn.wsd.device.wave.record'
    _description = 'Wave Soldering Data Record'
    _order = 'collect_time desc, id desc'
    _rec_name = 'device_sn'

    device_sn = fields.Char(string='Device SN', required=True, index=True)
    collect_time = fields.Datetime(
        string='Collection Time', required=True,
        help='Timestamp reported by the device (stored as UTC).')
    zone_line_ids = fields.One2many(
        'sn.wsd.device.wave.zone', 'wave_record_id',
        string='Temperature Data')
    zone_count = fields.Integer(
        string='Zone Count', compute='_compute_zone_count')

    def _compute_zone_count(self):
        for record in self:
            record.zone_count = len(record.zone_line_ids)


class WaveSolderingZone(models.Model):
    """Temperature of one heating zone inside a wave soldering data packet.

    The number of zones is decided by the device payload, hence stored as
    one line per zone instead of fixed columns.
    """
    _name = 'sn.wsd.device.wave.zone'
    _description = 'Wave Soldering Zone Temperature'
    _order = 'id'
    _rec_name = 'zone_name'

    wave_record_id = fields.Many2one(
        'sn.wsd.device.wave.record', string='Wave Record',
        required=True, ondelete='cascade', index=True)
    zone_name = fields.Char(string='Zone', required=True)
    temperature = fields.Float(string='Temperature', digits=(10, 2))
