from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Fixed day counts per cycle unit, per business spec (year=365, quarter=90).
CYCLE_UNIT_DAYS = {'quarterly': 90, 'yearly': 365}


class CalibrationPlan(models.Model):
    """Calibration plan: per equipment, at most two plans coexist
    (one certified + one non-certified), each with its own cycle."""
    _name = 'sn.wsd.device.cal.plan'
    _description = 'Equipment Calibration Plan'
    _order = 'equipment_id, is_certified desc, id'

    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment',
        required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(
        related='equipment_id.company_id', store=True,
        string='Company', index=True)
    equipment_code = fields.Char(
        related='equipment_id.code', store=True, string='Equipment Code')
    equipment_name = fields.Char(
        related='equipment_id.name', store=True, string='Equipment Name')
    equipment_model = fields.Char(
        related='equipment_id.model', store=True, string='Equipment Model')
    cycle_type = fields.Selection(
        selection=[
            ('quarterly', 'Quarterly'),
            ('yearly', 'Yearly'),
        ], string='Cycle Type', required=True, default='yearly')
    cycle_count = fields.Integer(
        string='Cycle Count', required=True, default=1,
        help='Number of cycle units between two calibrations. '
             'E.g. Quarterly x 2 = every 180 days.')
    initial_cal_date = fields.Date(
        string='Initial Calibration Date', required=True,
        help='Used as the last calibration date when the equipment ledger '
             'has no calibration date of this kind yet.')
    advance_days = fields.Integer(
        string='Advance Days', required=True, default=30,
        help='The task is generated this many days before the due date.')
    is_certified = fields.Boolean(
        string='Certified Calibration',
        help='If set, submitting the task requires a certificate file, '
             'number and validity date.')
    active = fields.Boolean(string='Active', default=True)

    _equipment_cert_unique = models.Constraint(
        'UNIQUE(equipment_id, is_certified)',
        'Only one certified and one non-certified calibration plan '
        'are allowed per equipment.')

    @api.constrains('cycle_count', 'advance_days')
    def _check_numbers(self):
        for plan in self:
            if plan.cycle_count < 1:
                raise ValidationError(_(
                    'The cycle count must be at least 1.'))
            if plan.advance_days < 0:
                raise ValidationError(_(
                    'The advance days cannot be negative.'))

    def _last_calibration_date(self):
        """Ledger date of this kind, falling back to the initial date."""
        self.ensure_one()
        equipment = self.equipment_id
        if self.is_certified:
            ledger_date = equipment.last_external_calibration_date
        else:
            ledger_date = equipment.last_internal_calibration_date
        return (ledger_date and ledger_date.date()) or self.initial_cal_date

    def _due_date(self):
        """Due date = last calibration + cycle unit days x cycle count."""
        self.ensure_one()
        from datetime import timedelta
        days = CYCLE_UNIT_DAYS[self.cycle_type] * self.cycle_count
        return self._last_calibration_date() + timedelta(days=days)

    def _task_creation_date(self):
        """Task creation date = due date - advance days."""
        self.ensure_one()
        from datetime import timedelta
        return self._due_date() - timedelta(days=self.advance_days)
