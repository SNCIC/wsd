from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
