# -*- coding: utf-8 -*-
"""Persistent record of each BOM Excel import run for auditability."""

from odoo import fields, models, _


class BomImportLog(models.Model):
    _name = 'sn.bom.import.log'
    _description = 'BOM Excel Import Log'
    _order = 'id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        default=lambda self: _('BOM Import %s') % fields.Datetime.now(),
    )
    file_name = fields.Char(string='Template File')
    state = fields.Selection(
        [('success', 'Success'), ('failed', 'Failed')],
        string='State',
        default='success',
    )
    bom_count = fields.Integer(string='BOMs Created', default=0)
    line_count = fields.Integer(string='Lines Created', default=0)
    skipped_count = fields.Integer(string='Existing Skipped', default=0)
    summary = fields.Text(string='Summary')
    create_date = fields.Datetime(string='Executed On', readonly=True)
