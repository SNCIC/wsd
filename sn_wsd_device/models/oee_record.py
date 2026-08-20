from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SHIFT_SELECTION = [
    ('all', 'All Day'),
    ('day', 'Day Shift'),
    ('night', 'Night Shift'),
]

DOWNTIME_REASON_SELECTION = [
    ('breakdown', 'Equipment Breakdown'),
    ('changeover', 'Changeover / Setup'),
    ('material', 'Material Shortage'),
    ('maintenance', 'Planned Maintenance'),
    ('power', 'Power Outage'),
    ('other', 'Other'),
]

# OEE level thresholds (in %) shared by list decorations, charts and reports.
OEE_LEVEL_EXCELLENT = 85.0
OEE_LEVEL_GOOD = 70.0
OEE_LEVEL_AVERAGE = 55.0


def compute_oee_metrics(planned_time, downtime_hours, design_capacity,
                        actual_output, qualified_qty):
    """Shared OEE math for records and batch entry lines.

    Returns the run time, theoretical output, unqualified qty, the three
    rates (in %) and the OEE value (in %).
    """
    run_hours = planned_time - downtime_hours
    theoretical_output = run_hours * design_capacity
    unqualified_qty = actual_output - qualified_qty
    availability_rate = (
        run_hours / planned_time * 100.0 if planned_time else 0.0)
    performance_rate = (
        actual_output / theoretical_output * 100.0
        if theoretical_output else 0.0)
    quality_rate = (
        qualified_qty / actual_output * 100.0 if actual_output else 0.0)
    oee_value = (
        availability_rate * performance_rate * quality_rate / 10000.0)
    return {
        'run_hours': run_hours,
        'theoretical_output': theoretical_output,
        'unqualified_qty': unqualified_qty,
        'availability_rate': availability_rate,
        'performance_rate': performance_rate,
        'quality_rate': quality_rate,
        'oee_value': oee_value,
    }


class OeeDowntime(models.Model):
    """One downtime reason line of an OEE record."""
    _name = 'sn.wsd.device.oee.downtime'
    _description = 'Equipment OEE Downtime Line'
    _order = 'id'

    record_id = fields.Many2one(
        'sn.wsd.device.oee.record', string='OEE Record',
        required=True, index=True, ondelete='cascade')
    reason = fields.Selection(
        selection=DOWNTIME_REASON_SELECTION, string='Downtime Reason',
        required=True, index=True)
    hours = fields.Float(string='Duration (h)', digits=(10, 2), required=True)
    remark = fields.Char(string='Remark')
    company_id = fields.Many2one(
        related='record_id.company_id', string='Company', store=True)


class OeeRecord(models.Model):
    """One OEE entry per equipment, date and shift.

    OEE = availability x performance x quality, where:
      availability = run time / planned working time
      performance = actual output / theoretical output
      quality = qualified qty / actual output
    """
    _name = 'sn.wsd.device.oee.record'
    _description = 'Equipment OEE Record'
    _order = 'date desc, id desc'
    _check_company_auto = True

    _equipment_date_shift_unique = models.Constraint(
        'unique(equipment_id, date, shift)',
        'One OEE record per equipment, date and shift.',
    )

    name = fields.Char(
        string='OEE Reference', default='/', copy=False, readonly=True,
        index=True)
    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment', required=True,
        index=True, ondelete='restrict', check_company=True)
    equipment_code = fields.Char(
        related='equipment_id.code', store=True, string='Equipment Code')
    equipment_name = fields.Char(
        related='equipment_id.name', string='Equipment Name')
    equipment_model = fields.Char(
        related='equipment_id.model', string='Equipment Model')
    date = fields.Date(
        string='Date', required=True, index=True,
        default=lambda self: fields.Date.context_today(self))
    shift = fields.Selection(
        selection=SHIFT_SELECTION, string='Shift', required=True,
        default='all', index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    note = fields.Char(string='Note')

    # ===== inputs =====
    planned_time = fields.Float(
        string='Planned Working Time (h)', digits=(10, 2), default=8.0)
    downtime_hours = fields.Float(
        string='Downtime (h)', digits=(10, 2), default=0.0, store=True,
        compute='_compute_downtime_hours', readonly=False,
        help='Automatically the sum of the downtime detail lines whenever at '
             'least one line exists. Enter a value manually only when there '
             'is no detail line.')
    downtime_ids = fields.One2many(
        'sn.wsd.device.oee.downtime', 'record_id', string='Downtime Details',
        copy=True)
    actual_output = fields.Integer(string='Actual Output (pcs)')
    qualified_qty = fields.Integer(string='Qualified Qty (pcs)')
    design_capacity = fields.Float(
        string='Design Capacity (pcs/h)', digits=(10, 1))

    # ===== results =====
    state = fields.Selection(
        selection=[('draft', 'Draft'), ('done', 'Computed')],
        string='Status', default='draft', index=True, copy=False)
    run_hours = fields.Float(
        string='Run Time (h)', digits=(10, 2),
        compute='_compute_oee_metrics', store=True)
    theoretical_output = fields.Float(
        string='Theoretical Output (pcs)', digits=(12, 1),
        compute='_compute_oee_metrics', store=True)
    unqualified_qty = fields.Integer(
        string='Unqualified Qty (pcs)',
        compute='_compute_oee_metrics', store=True)
    availability_rate = fields.Float(
        string='Availability (%)', digits=(10, 1),
        compute='_compute_oee_metrics', store=True)
    performance_rate = fields.Float(
        string='Performance (%)', digits=(10, 1),
        compute='_compute_oee_metrics', store=True)
    quality_rate = fields.Float(
        string='Quality Rate (%)', digits=(10, 1),
        compute='_compute_oee_metrics', store=True)
    oee_value = fields.Float(
        string='OEE (%)', digits=(10, 1),
        compute='_compute_oee_metrics', store=True, index=True)
    trend_data = fields.Json(
        string='OEE Trend Data', compute='_compute_trend_data')

    # ===== computes =====
    @api.depends('downtime_ids.hours')
    def _compute_downtime_hours(self):
        for record in self:
            record.downtime_hours = sum(
                line.hours for line in record.downtime_ids)

    @api.depends(
        'planned_time', 'downtime_hours', 'actual_output',
        'qualified_qty', 'design_capacity')
    def _compute_oee_metrics(self):
        for record in self:
            values = compute_oee_metrics(
                record.planned_time, record.downtime_hours,
                record.design_capacity, record.actual_output,
                record.qualified_qty)
            for field_name, value in values.items():
                record[field_name] = value

    def _compute_trend_data(self):
        today = fields.Date.context_today(self)
        start = today - timedelta(days=29)
        for record in self:
            if not record.equipment_id:
                record.trend_data = []
                continue
            recent = self.search([
                ('equipment_id', '=', record.equipment_id.id),
                ('state', '=', 'done'),
                ('date', '>=', start),
                ('date', '<=', today),
            ], order='date asc')
            per_date = {}
            for item in recent:
                per_date.setdefault(item.date, []).append(item)
            trend = []
            for day, records in sorted(per_date.items()):
                count = len(records)
                trend.append({
                    'date': day.strftime('%Y-%m-%d'),
                    'oee': round(sum(r.oee_value for r in records) / count, 1),
                    'availability': round(
                        sum(r.availability_rate for r in records) / count, 1),
                    'performance': round(
                        sum(r.performance_rate for r in records) / count, 1),
                    'quality': round(
                        sum(r.quality_rate for r in records) / count, 1),
                })
            record.trend_data = trend

    # ===== onchanges =====
    @api.onchange('equipment_id')
    def _onchange_equipment_id(self):
        """Keep the record company aligned with the picked equipment."""
        if self.equipment_id \
                and self.equipment_id.company_id != self.company_id:
            self.company_id = self.equipment_id.company_id

    # ===== constraints =====
    # Draft records stay freely editable (they may be partially filled);
    # business validation is enforced once a record is computed.
    @api.constrains(
        'state', 'planned_time', 'downtime_hours', 'design_capacity',
        'actual_output', 'qualified_qty')
    def _check_computed_values(self):
        for record in self:
            if record.state != 'done':
                continue
            if record.planned_time <= 0:
                raise ValidationError(_(
                    'Planned working time must be positive.'))
            if record.downtime_hours < 0 \
                    or record.downtime_hours > record.planned_time:
                raise ValidationError(_(
                    'Downtime must be between 0 and the planned working '
                    'time.'))
            if record.design_capacity <= 0:
                raise ValidationError(_(
                    'Design capacity must be positive.'))
            if record.actual_output < 0 or record.qualified_qty < 0:
                raise ValidationError(_(
                    'Output quantities cannot be negative.'))
            if record.qualified_qty > record.actual_output:
                raise ValidationError(_(
                    'Qualified qty cannot exceed the actual output.'))

    # ===== CRUD =====
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.device.oee.record') or '/'
        return super().create(vals_list)

    # ===== actions =====
    def action_compute_oee(self):
        """Validate the inputs and flag the record as computed."""
        for record in self:
            if record.planned_time <= 0:
                raise UserError(_('Please enter a positive planned working time.'))
            if record.downtime_hours > record.planned_time:
                raise UserError(_(
                    'Downtime cannot exceed the planned working time.'))
            if record.design_capacity <= 0:
                raise UserError(_('Please enter a positive design capacity.'))
            if record.actual_output <= 0:
                raise UserError(_('Please enter the actual output.'))
            if record.qualified_qty > record.actual_output:
                raise UserError(_(
                    'Qualified qty cannot exceed the actual output.'))
            record.state = 'done'
        first = self[0]
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('OEE Computed'),
                'message': _(
                    '%(equipment)s on %(date)s (%(shift)s): OEE %(oee).1f%% '
                    '(A %(availability).1f%% / P %(performance).1f%% / '
                    'Q %(quality).1f%%)',
                    equipment=first.equipment_id.display_name,
                    date=fields.Date.to_string(first.date),
                    shift=first._get_shift_label(),
                    oee=first.oee_value,
                    availability=first.availability_rate,
                    performance=first.performance_rate,
                    quality=first.quality_rate,
                ),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _get_shift_label(self):
        self.ensure_one()
        return dict(SHIFT_SELECTION).get(self.shift, self.shift)

    # ===== report data =====
    @api.model
    def get_report_data(self, date_from, date_to, equipment_ids=None):
        """Aggregated OEE payload for the client report action."""
        domain = [
            ('state', '=', 'done'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ]
        if equipment_ids:
            domain.append(('equipment_id', 'in', list(equipment_ids)))

        per_equipment = []
        groups = self._read_group(
            domain, ['equipment_id'],
            ['oee_value:avg', 'availability_rate:avg',
             'performance_rate:avg', 'quality_rate:avg',
             'actual_output:sum', 'downtime_hours:sum', '__count'])
        for (equipment, oee_avg, availability_avg, performance_avg,
                quality_avg, output_sum, downtime_sum, count) in groups:
            per_equipment.append({
                'equipment_id': equipment.id,
                'equipment_code': equipment.code or '',
                'equipment_name': equipment.name or '',
                'equipment_model': equipment.model or '',
                'oee': round(oee_avg or 0.0, 1),
                'availability': round(availability_avg or 0.0, 1),
                'performance': round(performance_avg or 0.0, 1),
                'quality': round(quality_avg or 0.0, 1),
                'output_total': int(output_sum or 0),
                'downtime_total': round(downtime_sum or 0.0, 1),
                'record_count': count,
            })
        per_equipment.sort(key=lambda item: item['oee'], reverse=True)

        trend = []
        for day, oee_avg in self._read_group(
                domain, ['date:day'], ['oee_value:avg']):
            trend.append({
                'date': day.strftime('%Y-%m-%d') if day else '',
                'oee': round(oee_avg or 0.0, 1),
            })
        trend.sort(key=lambda item: item['date'])

        distribution = {
            'excellent': 0, 'good': 0, 'average': 0, 'poor': 0,
        }
        for item in per_equipment:
            if item['oee'] >= OEE_LEVEL_EXCELLENT:
                distribution['excellent'] += 1
            elif item['oee'] >= OEE_LEVEL_GOOD:
                distribution['good'] += 1
            elif item['oee'] >= OEE_LEVEL_AVERAGE:
                distribution['average'] += 1
            else:
                distribution['poor'] += 1

        fleet = self._read_group(
            domain, [],
            ['oee_value:avg', 'availability_rate:avg',
             'performance_rate:avg', 'quality_rate:avg', '__count'])
        if fleet:
            oee_avg, availability_avg, performance_avg, quality_avg, count = \
                fleet[0]
        else:
            oee_avg = availability_avg = performance_avg = quality_avg = 0.0
            count = 0
        kpis = {
            'oee': round(oee_avg or 0.0, 1),
            'availability': round(availability_avg or 0.0, 1),
            'performance': round(performance_avg or 0.0, 1),
            'quality': round(quality_avg or 0.0, 1),
            'record_count': count,
            'equipment_count': len(per_equipment),
            'best': per_equipment[0] if per_equipment else None,
            'worst': per_equipment[-1] if len(per_equipment) > 1 else None,
        }
        return {
            'kpis': kpis,
            'per_equipment': per_equipment,
            'trend': trend,
            'distribution': distribution,
        }
