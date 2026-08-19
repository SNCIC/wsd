from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MaintenancePlan(models.Model):
    """Maintenance plan: one per equipment type, mirrors the spot check
    plan but generates maintenance tasks with their own trigger time."""
    _name = 'sn.wsd.device.maint.plan'
    _description = 'Equipment Maintenance Plan'
    _order = 'equipment_type_id, id'

    equipment_type_id = fields.Many2one(
        'sn.wsd.device.equipment.type', string='Equipment Type',
        required=True, index=True)
    equipment_type_code = fields.Char(
        related='equipment_type_id.code', store=True,
        string='Equipment Type Code')
    equipment_type_name = fields.Char(
        related='equipment_type_id.name', store=True,
        string='Equipment Type Name')
    cycle_type = fields.Selection(
        selection=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
            ('custom', 'Custom'),
        ], string='Cycle Type', required=True, default='monthly')
    custom_cycle_days = fields.Integer(
        string='Custom Cycle (days)',
        help='Used when the cycle type is Custom: the plan is due every '
             'N days starting from the start date.')
    start_date = fields.Date(
        string='Start Date', required=True,
        default=fields.Date.context_today)
    active = fields.Boolean(string='Active', default=True)

    _equipment_type_unique = models.Constraint(
        'UNIQUE(equipment_type_id)',
        'Only one maintenance plan per equipment type is allowed.')

    @api.constrains('cycle_type', 'custom_cycle_days')
    def _check_custom_cycle(self):
        for plan in self:
            if plan.cycle_type == 'custom' and plan.custom_cycle_days < 1:
                raise ValidationError(_(
                    'The custom cycle must be at least 1 day.'))

    def _is_equipment_due_today(self, equipment, today):
        """Per-equipment due rule, anchored on the last execution.

        The anchor is the equipment's last spot check date, falling back
        to the plan start date when the equipment was never checked. The
        distance to the anchor must be a multiple of the cycle:
        - a device EXECUTED today is never due again today (a full cycle
          must elapse from the last execution);
        - a device never executed is due on the plan start day itself
          and on every cycle multiple from it.
        """
        self.ensure_one()
        start = self.start_date
        if today < start:
            return False
        last = equipment.last_maintenance_date
        if last:
            anchor = last.date()
            require_full_cycle = True
        else:
            anchor = start
            require_full_cycle = False
        if self.cycle_type == 'daily':
            days = (today - anchor).days
            return days >= (1 if require_full_cycle else 0)
        if self.cycle_type == 'weekly':
            days = (today - anchor).days
            return days % 7 == 0 and (not require_full_cycle or days >= 7)
        if self.cycle_type == 'custom':
            days = (today - anchor).days
            cycle = self.custom_cycle_days
            return days % cycle == 0 and                 (not require_full_cycle or days >= cycle)
        months_step = 1 if self.cycle_type == 'monthly' else 3
        month_index = ((today.year - anchor.year) * 12
                       + (today.month - anchor.month))
        if month_index % months_step:
            return False
        if require_full_cycle and month_index < months_step:
            return False
        return anchor + relativedelta(months=month_index) == today
