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
    def _parameter_trigger_datetime(self, now):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'equipment_cal_trigger_time', '08:00')
        try:
            hour_str, minute_str = raw.strip().split(':')
            hour, minute = int(hour_str), int(minute_str)
            assert 0 <= hour <= 23 and 0 <= minute <= 59
        except (ValueError, AssertionError):
            hour, minute = 8, 0
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


class CalibrationPlan(models.Model):
    """Add the shared calibration cron entry point to the plan model."""

    _inherit = 'sn.wsd.device.cal.plan'

    @api.model
    def _cron_generate_calibration_tasks(self):
        """Single shared cron for every calibration plan. Wakes up every
        10 minutes, waits until the calibration trigger time, then for
        each plan whose task creation date is reached: marks previous
        unfinished same-kind tasks overdue and generates a new task
        (one run per plan per day, the log is the idempotency token)."""
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        trigger_dt = self.env[
            'sn.wsd.device.cal.generation.log']._parameter_trigger_datetime(now)
        if now < trigger_dt:
            return
        log_model = self.env['sn.wsd.device.cal.generation.log']
        task_model = self.env['sn.wsd.device.cal.task']
        for plan in self.search([('active', '=', True)]):
            already_logged = log_model.search_count([
                ('plan_id', '=', plan.id),
                ('generation_date', '=', today),
            ])
            if already_logged:
                continue
            plan._generate_task_for_today(today, now, trigger_dt,
                                          log_model, task_model)

    def _generate_task_for_today(self, today, now, trigger_dt,
                                 log_model, task_model):
        self.ensure_one()
        equipment = self.equipment_id
        due_date = self._due_date()
        creation_date = self._task_creation_date()
        generated = skipped = failed = 0
        errors = []
        if today < creation_date:
            # Not due yet: nothing to do, no log (avoid noise).
            return
        if equipment.equipment_status not in ('enabled', 'repair'):
            skipped = 1
        else:
            # Business rule chosen by the customer: unfinished tasks of
            # the same certification kind are marked overdue and a new
            # task is still generated.
            unfinished = task_model.search([
                ('equipment_id', '=', equipment.id),
                ('is_certified', '=', self.is_certified),
                ('task_status', 'in', ['pending', 'in_progress']),
            ])
            unfinished.write({'task_status': 'overdue'})
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
        run_status = 'failed' if failed else 'success'
        log_model.create({
            'plan_id': self.id,
            'generation_date': today,
            'trigger_time': f'{trigger_dt.hour:02d}:{trigger_dt.minute:02d}',
            'due_date': due_date,
            'task_creation_date': creation_date,
            'generated_count': generated,
            'skipped_count': skipped,
            'failed_count': failed,
            'run_status': run_status,
            'error_detail': '\n'.join(errors) or False,
            'execution_time': now,
        })
