# -*- coding: utf-8 -*-
"""Work-center ↔ equipment association line.

Thin link model: which equipment belongs to which work center, plus a
hand-typed sequence giving the process order of the machines on the line."""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WorkcenterEquipment(models.Model):
    _name = 'sn.wsd.workcenter.equipment'
    _description = 'Work Center Equipment'
    # REQ-010: 清单按手工录入的顺序升序，同序按加入先后稳定排列
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Work Center',
        required=True, index=True, ondelete='cascade')
    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment',
        required=True, index=True, ondelete='cascade')
    equipment_code = fields.Char(
        related='equipment_id.code', string='Equipment Code')
    equipment_name = fields.Char(
        related='equipment_id.name', string='Equipment Name')
    company_id = fields.Many2one(
        'res.company', string='Company',
        related='workcenter_id.company_id', store=True, index=True)

    @api.constrains('equipment_id')
    def _check_equipment_single_workcenter(self):
        # REQ-009: 一台设备同一时间只允许归属一个工作中心
        for line in self:
            duplicate = self.search([
                ('equipment_id', '=', line.equipment_id.id),
                ('id', '!=', line.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Equipment %(equipment)s is already assigned to work '
                    'center %(workcenter)s. Remove it there first.',
                    equipment=line.equipment_id.display_name,
                    workcenter=duplicate.workcenter_id.display_name,
                ))
