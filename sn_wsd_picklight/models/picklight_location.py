from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PicklightShelf(models.Model):
    _name = 'sn.wsd.picklight.shelf'
    _description = 'Picklight Shelf'
    _check_company_auto = True
    _order = 'code, id'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Shelf Code', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one(
        'sn.wsd.picklight.config', string='Service Configuration',
        required=True, check_company=True)
    active = fields.Boolean(string='Active', default=True)
    location_ids = fields.One2many(
        'sn.wsd.picklight.location', 'shelf_id', string='Picklight Locations')
    battery_level = fields.Integer(string='Battery (%)', readonly=True)
    humidity = fields.Float(string='Humidity (%)', readonly=True)
    temperature = fields.Float(string='Temperature', readonly=True)
    last_sensor_at = fields.Datetime(string='Last Sensor Reading', readonly=True)

    _unique_company_code = models.Constraint(
        'unique(company_id, code)',
        'A shelf code must be unique per company.')

    @api.constrains('config_id')
    def _check_config_company(self):
        for record in self:
            if record.config_id and record.config_id.company_id != record.company_id:
                raise ValidationError(_('The shelf and service configuration must use the same company.'))


class PicklightLocation(models.Model):
    _name = 'sn.wsd.picklight.location'
    _description = 'Picklight Location'
    _check_company_auto = True
    _order = 'shelf_id, code'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Location Code', required=True, index=True)
    shelf_id = fields.Many2one(
        'sn.wsd.picklight.shelf', string='Shelf', required=True,
        ondelete='cascade', check_company=True)
    stock_location_id = fields.Many2one(
        'stock.location', string='Odoo Stock Location', required=True,
        ondelete='restrict', check_company=True)
    company_id = fields.Many2one(
        related='shelf_id.company_id', store=True, readonly=True)
    light_color = fields.Integer(string='Default Light Color', default=64)
    twinkle = fields.Boolean(string='Twinkle')
    is_locked = fields.Boolean(string='Locked')
    is_must_collect = fields.Boolean(string='Must Collect')
    active = fields.Boolean(string='Active', default=True)

    _unique_shelf_code = models.Constraint(
        'unique(shelf_id, code)',
        'A location code must be unique per shelf.')
    _unique_stock_location = models.Constraint(
        'unique(company_id, stock_location_id)',
        'An Odoo stock location can only map to one active picklight location.')

    def _send_debug_command(self, light_on):
        """Light up (or turn off) the selected locations for debugging.

        Commands are grouped by service configuration so each picklight
        server receives one PostInfo request.
        """
        locations = self.filtered('shelf_id.config_id')
        if not locations:
            raise UserError(_('The selected locations are not linked to any service configuration.'))
        grouped = {}
        for location in locations:
            grouped.setdefault(location.shelf_id.config_id, []).append(location)
        for config, locs in grouped.items():
            details = []
            for location in locs:
                if light_on:
                    light_color = location.light_color or 64
                    quantity = 1
                else:
                    light_color = 0
                    quantity = 0
                details.append({
                    'LocationId': location.code,
                    'LightColor': light_color,
                    'Twinkle': int(location.twinkle) if light_on else 0,
                    'IsLocked': int(location.is_locked) if light_on else 0,
                    'IsMustCollect': int(location.is_must_collect) if light_on else 0,
                    'Quantity': quantity,
                    'SubText': location.code,
                    'BatchCode': '',
                    'Name': location.name or location.code,
                    'R1': location.code,
                    'R2': '',
                    'R3': '',
                    'SubTitle': '',
                    'Title': 'Pick',
                    'Unit': '',
                    'RelateToTower': True,
                })
            command = self.env['sn.wsd.picklight.command'].create({
                'company_id': config.company_id.id,
                'config_id': config.id,
                'command_type': 'post_info',
                'endpoint': config.endpoint_url('/api/Light/PostInfo/'),
                'request_payload': {'TwinkleTime': 0, 'Details': details},
            })
            command.send()
        return True

    def action_light_on(self):
        """Test button: light up the selected location(s)."""
        return self._send_debug_command(True)

    def action_light_off(self):
        """Test button: turn off the selected location(s)."""
        return self._send_debug_command(False)
