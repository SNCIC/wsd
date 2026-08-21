# -*- coding: utf-8 -*-
"""Work-center fields used by the shop-floor station terminal.

Only the terminal bits: which work centers show up on the terminal and
which employees may operate them. The work-order costing/blocking pieces
that used to live here were removed together with the work-order flows."""

from odoo import fields, models


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    sn_shop_floor_employee_ids = fields.Many2many(
        'hr.employee',
        'sn_wsd_workcenter_employee_rel',
        'workcenter_id',
        'employee_id',
        string='Shop Floor Employees',
        help='If empty, every employee from the active companies can work '
             'on this work center.',
    )
    sn_shop_floor_enabled = fields.Boolean(
        string='Show on Shop Floor', default=True)
    sn_equipment_ids = fields.One2many(
        'sn.wsd.workcenter.equipment', 'workcenter_id', string='Equipment',
        help='Equipment assigned to this work center; the hand-typed '
             'sequence gives the process order of the machines.')

    def sn_get_employee_by_barcode(self, barcode):
        return self.env['hr.employee'].sudo().search(
            [('barcode', '=', barcode)], limit=1).id
