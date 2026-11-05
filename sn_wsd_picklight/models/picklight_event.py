from odoo import fields, models


class PicklightEvent(models.Model):
    _name = 'sn.wsd.picklight.event'
    _description = 'Picklight Device Event'
    _order = 'event_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', required=True, copy=False)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        index=True)
    event_type = fields.Selection([
        ('status_changed', 'Status Changed'),
        ('pressed', 'PTL Pressed'),
        ('scan_changed', 'Scan Changed'),
        ('self_checking', 'Self Checking'),
    ], string='Event Type', required=True)
    location_code = fields.Char(string='Location Code', index=True)
    shelf_code = fields.Char(string='Shelf Code', index=True)
    barcode = fields.Char(string='Barcode')
    state = fields.Integer(string='State')
    quantity = fields.Integer(string='Quantity')
    light_color = fields.Integer(string='Light Color')
    batch_code = fields.Char(string='Batch Code')
    event_time = fields.Datetime(string='Event Time', required=True)
    payload = fields.Json(string='Payload')
    stock_location_id = fields.Many2one(
        'stock.location', string='Odoo Stock Location', check_company=True)
    picking_id = fields.Many2one(
        'stock.picking', string='Transfer', check_company=True)
    processed = fields.Boolean(string='Processed')
    processing_message = fields.Text(string='Processing Message')
