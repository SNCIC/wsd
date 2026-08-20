import calendar
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from .oee_record import SHIFT_SELECTION, compute_oee_metrics


class OeeBatchWizard(models.TransientModel):
    """Enter one month of daily OEE data for one equipment in one screen."""
    _name = 'sn.wsd.device.oee.batch.wizard'
    _description = 'OEE Batch Entry'

    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment', required=True,
        index=True, ondelete='cascade')
    month = fields.Selection(
        selection='_selection_month', string='Month', required=True,
        default=lambda self: self._selection_month()[0][0])
    shift = fields.Selection(
        selection=SHIFT_SELECTION, string='Shift', required=True,
        default='all')
    planned_time = fields.Float(
        string='Planned Working Time (h)', digits=(10, 2), default=8.0,
        help='Default value used when the daily lines are generated.')
    design_capacity = fields.Float(
        string='Design Capacity (pcs/h)', digits=(10, 1),
        help='Default value used when the daily lines are generated.')
    line_ids = fields.One2many(
        'sn.wsd.device.oee.batch.line', 'wizard_id', string='Daily Lines')

    @api.model
    def _selection_month(self):
        """The current month plus the twelve previous ones."""
        first_of_month = fields.Date.context_today(self).replace(day=1)
        months = []
        for offset in range(13):
            month_start = first_of_month - relativedelta(months=offset)
            key = month_start.strftime('%Y-%m')
            months.append((key, key))
        return months

    def _month_days(self):
        """All days of the selected month, capped at today."""
        self.ensure_one()
        year, month = (int(part) for part in self.month.split('-'))
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        last = min(last, fields.Date.context_today(self))
        if last < first:
            return []
        return [date(year, month, day) for day in range(1, last.day + 1)]

    def _fill_days(self):
        """Rebuild one line per day of the month with the wizard defaults."""
        self.line_ids = [
            Command.create({
                'date': day,
                'planned_time': self.planned_time,
                'design_capacity': self.design_capacity,
            })
            for day in self._month_days()
        ]

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards:
            if not wizard.line_ids:
                wizard._fill_days()
        return wizards

    @api.onchange('month')
    def _onchange_month(self):
        """Changing the month rebuilds the daily lines."""
        self._fill_days()

    def action_create_records(self):
        """Create one OEE record per filled line.

        Lines without actual output are skipped. Existing records of the
        same equipment, shift and date are replaced.
        """
        self.ensure_one()
        record_model = self.env['sn.wsd.device.oee.record']
        to_create = []
        skipped = 0
        for line in self.line_ids:
            if not line.actual_output:
                skipped += 1
                continue
            if line.planned_time <= 0:
                raise UserError(_(
                    'Line of %(date)s: planned working time must be '
                    'positive.', date=fields.Date.to_string(line.date)))
            if line.downtime_hours < 0 \
                    or line.downtime_hours > line.planned_time:
                raise UserError(_(
                    'Line of %(date)s: downtime must be between 0 and the '
                    'planned working time.',
                    date=fields.Date.to_string(line.date)))
            if line.design_capacity <= 0:
                raise UserError(_(
                    'Line of %(date)s: design capacity must be positive.',
                    date=fields.Date.to_string(line.date)))
            if line.qualified_qty > line.actual_output:
                raise UserError(_(
                    'Line of %(date)s: qualified qty cannot exceed the '
                    'actual output.', date=fields.Date.to_string(line.date)))
            to_create.append(line)

        dates = [line.date for line in to_create]
        replaced = 0
        if dates:
            existing = record_model.search([
                ('equipment_id', '=', self.equipment_id.id),
                ('shift', '=', self.shift),
                ('date', 'in', dates),
            ])
            replaced = len(existing)
            existing.unlink()

        record_model.create([{
            'equipment_id': self.equipment_id.id,
            'company_id': self.equipment_id.company_id.id,
            'date': line.date,
            'shift': self.shift,
            'planned_time': line.planned_time,
            'downtime_hours': line.downtime_hours,
            'actual_output': line.actual_output,
            'qualified_qty': line.qualified_qty,
            'design_capacity': line.design_capacity,
            'state': 'done',
        } for line in to_create])

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('OEE Records Created'),
                'message': _(
                    '%(created)s record(s) created for %(equipment)s '
                    '(%(month)s / %(shift)s), %(replaced)s existing '
                    'record(s) replaced, %(skipped)s day(s) skipped.',
                    created=len(to_create),
                    equipment=self.equipment_id.display_name,
                    month=self.month,
                    shift=dict(SHIFT_SELECTION).get(self.shift, self.shift),
                    replaced=replaced,
                    skipped=skipped,
                ),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class OeeBatchLine(models.TransientModel):
    """One day of the batch entry grid."""
    _name = 'sn.wsd.device.oee.batch.line'
    _description = 'OEE Batch Entry Line'
    _order = 'date, id'

    wizard_id = fields.Many2one(
        'sn.wsd.device.oee.batch.wizard', string='Batch Entry',
        required=True, index=True, ondelete='cascade')
    date = fields.Date(string='Date', required=True)
    planned_time = fields.Float(
        string='Planned Working Time (h)', digits=(10, 2), default=8.0)
    downtime_hours = fields.Float(
        string='Downtime (h)', digits=(10, 2), default=0.0)
    design_capacity = fields.Float(
        string='Design Capacity (pcs/h)', digits=(10, 1))
    actual_output = fields.Integer(string='Actual Output (pcs)')
    qualified_qty = fields.Integer(string='Qualified Qty (pcs)')

    # ===== live preview (same math as the OEE record) =====
    run_hours = fields.Float(
        string='Run Time (h)', digits=(10, 2), compute='_compute_metrics')
    theoretical_output = fields.Float(
        string='Theoretical Output (pcs)', digits=(12, 1),
        compute='_compute_metrics')
    unqualified_qty = fields.Integer(
        string='Unqualified Qty (pcs)', compute='_compute_metrics')
    availability_rate = fields.Float(
        string='Availability (%)', digits=(10, 1),
        compute='_compute_metrics')
    performance_rate = fields.Float(
        string='Performance (%)', digits=(10, 1),
        compute='_compute_metrics')
    quality_rate = fields.Float(
        string='Quality Rate (%)', digits=(10, 1),
        compute='_compute_metrics')
    oee_value = fields.Float(
        string='OEE (%)', digits=(10, 1), compute='_compute_metrics')

    @api.depends(
        'planned_time', 'downtime_hours', 'design_capacity',
        'actual_output', 'qualified_qty')
    def _compute_metrics(self):
        for line in self:
            values = compute_oee_metrics(
                line.planned_time, line.downtime_hours,
                line.design_capacity, line.actual_output,
                line.qualified_qty)
            for field_name, value in values.items():
                line[field_name] = value
