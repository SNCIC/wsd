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

    def _is_due_today(self, today):
        """Calendar-aware due computation from the start date."""
        self.ensure_one()
        start = self.start_date
        if today < start:
            return False
        if self.cycle_type == 'daily':
            return True
        if self.cycle_type == 'weekly':
            return (today - start).days % 7 == 0
        if self.cycle_type == 'custom':
            return (today - start).days % self.custom_cycle_days == 0
        months_step = 1 if self.cycle_type == 'monthly' else 3
        month_index = ((today.year - start.year) * 12
                       + (today.month - start.month))
        if month_index % months_step:
            return False
        return start + relativedelta(months=month_index) == today

    def _is_equipment_due_today(self, equipment, today):
        """Per-equipment due rule.

        Daily plans are due every day (the same-day-done skip in the
        generation loop keeps one task per day). Weekly plans anchor on
        the equipment's last maintenance date: due 7 days after it, so
        the rhythm follows the actual completion date; equipment never
        maintained falls back to the plan start date. Other cycle types
        stay anchored on the plan start date.
        """
        self.ensure_one()
        start = self.start_date
        if today < start:
            return False
        if self.cycle_type == 'daily':
            return True
        if self.cycle_type == 'weekly':
            last = equipment.last_maintenance_date
            anchor = last.date() if last else start
            return (today - anchor).days % 7 == 0
        return self._is_due_today(today)
