import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PicklightCommand(models.Model):
    _name = 'sn.wsd.picklight.command'
    _description = 'Picklight Command'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', required=True, copy=False, default='New')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        index=True)
    config_id = fields.Many2one(
        'sn.wsd.picklight.config', string='Configuration',
        required=True, check_company=True)
    picking_id = fields.Many2one(
        'stock.picking', string='Transfer', check_company=True, index=True)
    command_type = fields.Selection([
        ('post_info', 'Light Locations'),
        ('light_shelf', 'Light Shelves'),
        ('light_ibs', 'Light IBS'),
        ('checking', 'Service Check'),
        ('get_location_state', 'Get Location State'),
        ('get_battery', 'Get Battery'),
        ('get_ths', 'Get Temperature and Humidity'),
    ], string='Command Type', required=True)
    endpoint = fields.Char(string='Endpoint', required=True)
    request_payload = fields.Json(string='Request Payload')
    response_payload = fields.Json(string='Response Payload')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ], string='State', default='draft', required=True, index=True)
    result_code = fields.Integer(string='Result Code')
    message = fields.Text(string='Message')
    sent_at = fields.Datetime(string='Sent At')
    finished_at = fields.Datetime(string='Finished At')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.picklight.command') or '/'
        return super().create(vals_list)

    def send(self):
        self.ensure_one()
        payload = self.request_payload or {}
        self.write({'state': 'draft', 'sent_at': fields.Datetime.now()})
        try:
            response = requests.post(
                self.endpoint, json=payload,
                headers=({
                    'Content-Type': 'application/json',
                    **({'X-API-Token': self.config_id.api_token}
                       if self.config_id.api_token else {}),
                }),
                timeout=self.config_id.timeout_seconds)
            try:
                response_data = response.json()
            except ValueError:
                response_data = {'raw': response.text}
            result_code = response_data.get('Result') if isinstance(response_data, dict) else False
            ok = response.ok and (result_code in (False, None, 1))
            self.write({
                'response_payload': response_data,
                'result_code': result_code or response.status_code,
                'state': 'sent' if ok else 'failed',
                'message': response_data.get('Message') if isinstance(response_data, dict) else response.text,
                'finished_at': fields.Datetime.now(),
            })
            if not ok:
                raise UserError(_(
                    'The picklight service rejected the command: %s',
                    self.message or response.text))
            return response_data
        except requests.RequestException as error:
            _logger.exception('Picklight command failed: %s', self.endpoint)
            self.write({
                'state': 'failed',
                'message': str(error),
                'finished_at': fields.Datetime.now(),
            })
            raise UserError(_('The picklight service is unavailable: %s', error)) from error
