# -*- coding: utf-8 -*-
"""Configurable scrap reasons, stamped on native scrap orders."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SnWsdScrapReason(models.Model):
    _name = 'sn.wsd.scrap.reason'
    _description = 'Scrap Reason'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True,
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for reason in self:
            reason.display_name = '%s %s' % (reason.code, reason.name)                 if reason.code else reason.name


class StockScrapReason(models.Model):
    _inherit = 'stock.scrap'

    x_scrap_reason_id = fields.Many2one(
        'sn.wsd.scrap.reason', string='MES Scrap Reason', index=True,
        ondelete='set null',
    )
