from odoo import api, fields, models


class PicklightSensorReading(models.Model):
    _name = 'sn.wsd.picklight.sensor.reading'
    _description = 'Picklight Sensor Reading'
    _order = 'reading_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', required=True, copy=False)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        index=True)
    config_id = fields.Many2one(
        'sn.wsd.picklight.config', string='Configuration',
        required=True, check_company=True)
    shelf_id = fields.Many2one(
        'sn.wsd.picklight.shelf', string='Shelf', required=True,
        check_company=True, index=True)
    reading_type = fields.Selection([
        ('battery', 'Battery'),
        ('temperature_humidity', 'Temperature and Humidity'),
    ], string='Reading Type', required=True)
    battery_level = fields.Integer(string='Battery (%)')
    humidity = fields.Float(string='Humidity (%)')
    temperature = fields.Float(string='Temperature')
    reading_time = fields.Datetime(string='Reading Time', required=True)
    request_payload = fields.Json(string='Request Payload')
    response_payload = fields.Json(string='Response Payload')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('name', 'New')
            if vals['name'] == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.picklight.sensor') or '/'
        records = super().create(vals_list)
        for record in records:
            values = {'last_sensor_at': record.reading_time}
            if record.reading_type == 'battery':
                values['battery_level'] = record.battery_level
            else:
                values.update({
                    'humidity': record.humidity,
                    'temperature': record.temperature,
                })
            record.shelf_id.write(values)
        return records
