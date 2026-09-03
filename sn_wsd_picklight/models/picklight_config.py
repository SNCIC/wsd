from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PicklightConfig(models.Model):
    _name = 'sn.wsd.picklight.config'
    _description = 'Picklight Service Configuration'
    _check_company_auto = True
    _order = 'company_id, name'

    name = fields.Char(string='Name', required=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True)
    base_url = fields.Char(
        string='Service Base URL', required=True,
        help='For example http://127.0.0.1:9090')
    api_token = fields.Char(string='API Token')
    timeout_seconds = fields.Integer(
        string='Timeout (seconds)', default=10, required=True)
    active = fields.Boolean(string='Active', default=True)
    note = fields.Text(string='Notes')

    _unique_company_name = models.Constraint(
        'unique(company_id, name)',
        'A picklight configuration name must be unique per company.')

    @api.constrains('base_url', 'timeout_seconds')
    def _check_values(self):
        for record in self:
            if not record.base_url.startswith(('http://', 'https://')):
                raise ValidationError(_('The service base URL must start with http:// or https://.'))
            if record.timeout_seconds <= 0:
                raise ValidationError(_('The timeout must be greater than zero.'))

    @api.model
    def get_active(self, company=None):
        company = company or self.env.company
        records = self.search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], order='id', limit=1)
        return records

    def endpoint_url(self, path):
        self.ensure_one()
        return self.base_url.rstrip('/') + '/' + path.lstrip('/')

    def _call(self, command_type, path, payload, shelf=False):
        self.ensure_one()
        command = self.env['sn.wsd.picklight.command'].create({
            'company_id': self.company_id.id,
            'config_id': self.id,
            'command_type': command_type,
            'endpoint': self.endpoint_url(path),
            'request_payload': payload,
        })
        response = command.send()
        if shelf and isinstance(response, dict):
            sensor_model = self.env['sn.wsd.picklight.sensor.reading']
            if command_type == 'get_battery':
                result = response.get('shelfTab') or {}
                sensor_model.create({
                    'company_id': self.company_id.id,
                    'config_id': self.id,
                    'shelf_id': shelf.id,
                    'reading_type': 'battery',
                    'battery_level': result.get('Power'),
                    'reading_time': fields.Datetime.now(),
                    'request_payload': payload,
                    'response_payload': response,
                })
            elif command_type == 'get_ths':
                result = response.get('shelfThs') or {}
                sensor_model.create({
                    'company_id': self.company_id.id,
                    'config_id': self.id,
                    'shelf_id': shelf.id,
                    'reading_type': 'temperature_humidity',
                    'humidity': result.get('Humidity'),
                    'temperature': result.get('Temperature'),
                    'reading_time': fields.Datetime.now(),
                    'request_payload': payload,
                    'response_payload': response,
                })
        return response

    def light_shelf(self, shelf_codes, light_color):
        self.ensure_one()
        return self._call('light_shelf', '/api/Light/LightShelf/', {
            'Shelf': shelf_codes,
            'LightColor': light_color,
        })

    def light_ibs(self, ibs_models):
        self.ensure_one()
        return self._call('light_ibs', '/api/Light/LightIBS/', {
            'IbsModelList': ibs_models,
        })

    def query_battery(self, shelf):
        self.ensure_one()
        return self._call('get_battery', '/api/Light/BatterySearch/', {
            'Shelf': shelf.code,
        }, shelf=shelf)

    def query_temperature_humidity(self, shelf):
        self.ensure_one()
        return self._call('get_ths', '/api/Light/THSSearch/', {
            'Shelf': shelf.code,
        }, shelf=shelf)
