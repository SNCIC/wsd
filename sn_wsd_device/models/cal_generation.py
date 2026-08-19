from datetime import timedelta, timezone

from odoo import api, fields, models


class CalibrationGenerationLog(models.Model):
    """Audit trail of one calibration plan run of the shared cron."""
    _name = 'sn.wsd.device.cal.generation.log'
    _description = 'Calibration Generation Log'
    _order = 'id desc'

    plan_id = fields.Many2one(
        'sn.wsd.device.cal.plan', string='Calibration Plan',
        required=True, index=True, ondelete='cascade')
    plan_equipment = fields.Char(
        related='plan_id.equipment_code', store=True,
        string='Plan Equipment')
    generation_date = fields.Date(
        string='Generation Date', required=True, index=True)
    trigger_time = fields.Char(string='Trigger Time')
    due_date = fields.Date(string='Due Date')
    task_creation_date = fields.Date(string='Task Creation Date')
    generated_count = fields.Integer(string='Generated Count')
    skipped_count = fields.Integer(string='Skipped Count')
    failed_count = fields.Integer(string='Failed Count')
    run_status = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('partial', 'Partial'),
            ('failed', 'Failed'),
        ], string='Run Status', required=True)
    error_detail = fields.Text(string='Error Detail')
    execution_time = fields.Datetime(string='Execution Time')


    @api.model
    def _parameter_trigger_time_display(self):
        """The configured business trigger time (local wall clock), as
        shown on generation logs."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'equipment_cal_trigger_time', '08:00')
        return (raw or '08:00').strip()

    @api.model
    def _parameter_trigger_datetime(self, now):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'equipment_cal_trigger_time', '08:00')
        try:
            hour_str, minute_str = raw.strip().split(':')
            hour, minute = int(hour_str), int(minute_str)
            assert 0 <= hour <= 23 and 0 <= minute <= 59
        except (ValueError, AssertionError):
            hour, minute = 8, 0
        # The parameter is a business wall-clock time: interpret it in the
        # current user timezone (falling back to the administrator's, then
        # UTC for cron runs) and convert back to UTC, because `now` and the
        # stored datetimes are UTC.
        tz_name = (
            self.env.context.get('tz')
            or self.env.user.tz
            or self.env.ref('base.user_admin').sudo().tz
            or 'UTC')
        local_now = fields.Datetime.context_timestamp(
            self.with_context(tz=tz_name), now)
        trigger_local = local_now.replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        return trigger_local.astimezone(
            timezone.utc).replace(tzinfo=None)


class CalibrationPlan(models.Model):
    """Add the shared calibration cron entry point to the plan model."""

    _inherit = 'sn.wsd.device.cal.plan'

    @api.model
    def _cron_generate_calibration_tasks(self):
        """Single shared cron for every calibration plan. Wakes up every
        minute; the scheduled pass executes once per day, shortly after
        the calibration trigger time, and for each plan whose task
        creation date is reached: marks previous unfinished same-kind
        tasks overdue and generates a new task."""
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        trigger_dt = self.env[
            'sn.wsd.device.cal.generation.log']._parameter_trigger_datetime(now)
        if now < trigger_dt:
            return
        # Once-per-day semantics: the scheduled pass executes only on the
        # wake-ups shortly after the daily trigger time (the first tick at
        # or after it); later wake-ups stay no-ops until tomorrow.
        if now > trigger_dt + timedelta(minutes=15):
            return
        log_model = self.env['sn.wsd.device.cal.generation.log']
        task_model = self.env['sn.wsd.device.cal.task']
        for plan in self.search([('active', '=', True)]):
            # No plan-level log gate: the once-per-day window above decides
            # whether the scheduled pass runs at all.
            plan._generate_task_for_today(today, now, trigger_dt,
                                          log_model, task_model)

    def _generate_task_for_today(self, today, now, trigger_dt,
                                 log_model, task_model):
        self.ensure_one()
        equipment = self.equipment_id
        due_date = self._due_date()
        creation_date = self._task_creation_date()
        generated = skipped = failed = 0
        overdue_marked = 0
        errors = []
        # Overdue rule: at the daily refresh, unfinished tasks of a cycle
        # whose due date (last calibration or initial date + cycle x count)
        # has already passed become overdue.
        open_tasks = task_model.search([
            ('plan_id', '=', self.id),
            ('task_status', 'in', ['pending', 'in_progress']),
        ])
        overdue_tasks = open_tasks.filtered(lambda task: today > due_date)
        overdue_tasks.write({'task_status': 'overdue'})
        overdue_marked = len(overdue_tasks)
        if today < creation_date:
            # Not due yet: nothing to generate (log only if the overdue
            # pass marked something, otherwise stay silent).
            if not overdue_marked:
                return
            log_model.create({
                'plan_id': self.id,
                'generation_date': today,
                'trigger_time': log_model._parameter_trigger_time_display(),
                'due_date': due_date,
                'task_creation_date': creation_date,
                'generated_count': 0,
                'skipped_count': 0,
                'failed_count': 0,
                'run_status': 'success',
                'error_detail': False,
                'execution_time': now,
            })
            return
        if equipment.equipment_status not in ('enabled', 'repair'):
            skipped = 1
        elif open_tasks:
            # This cycle already has an open task: the plan waits for its
            # completion (completion moves the calibration anchor and
            # re-arms the next cycle).
            skipped = 1
        else:
            try:
                task_model.create({
                    'plan_id': self.id,
                    'equipment_id': equipment.id,
                    'task_date': today,
                    'responsible_user_id': equipment.calibration_user_id.id,
                })
                generated = 1
            except Exception as exc:  # noqa: BLE001 - logged, not fatal
                failed = 1
                errors.append(f'{equipment.code}: {exc}')
        # Log only runs that produced something: pure-skip wake-ups must
        # not flood the generation log.
        if not generated and not failed and not overdue_marked:
            return
        run_status = 'failed' if failed else 'success'
        log_model.create({
            'plan_id': self.id,
            'generation_date': today,
            'trigger_time': log_model._parameter_trigger_time_display(),
            'due_date': due_date,
            'task_creation_date': creation_date,
            'generated_count': generated,
            'skipped_count': skipped,
            'failed_count': failed,
            'run_status': run_status,
            'error_detail': '\n'.join(errors) or False,
            'execution_time': now,
        })
