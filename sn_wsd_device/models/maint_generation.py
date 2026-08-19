from odoo import api, fields, models
from odoo.fields import Command
from datetime import timezone


class MaintenanceGenerationLog(models.Model):
    """Audit trail of one maintenance plan run of the shared cron."""
    _name = 'sn.wsd.device.maint.generation.log'
    _description = 'Maintenance Generation Log'
    _order = 'id desc'

    plan_id = fields.Many2one(
        'sn.wsd.device.maint.plan', string='Maintenance Plan',
        required=True, index=True, ondelete='cascade')
    plan_equipment_type = fields.Char(
        related='plan_id.equipment_type_name', store=True,
        string='Plan Equipment Type')
    generation_date = fields.Date(
        string='Generation Date', required=True, index=True)
    trigger_time = fields.Char(string='Trigger Time')
    expected_equipment_count = fields.Integer(
        string='Expected Equipment Count')
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
        """Parse the maintenance trigger time parameter (independent of
        the spot check one)."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'equipment_maintenance_trigger_time', '08:30')
        try:
            hour_str, minute_str = raw.strip().split(':')
            hour, minute = int(hour_str), int(minute_str)
            assert 0 <= hour <= 23 and 0 <= minute <= 59
        except (ValueError, AssertionError):
            hour, minute = 8, 30
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


class MaintenancePlan(models.Model):
    """Add the shared maintenance cron entry point to the plan model."""

    _inherit = 'sn.wsd.device.maint.plan'

    @api.model
    def _cron_generate_maintenance_tasks(self):
        """Single shared cron for every maintenance plan. Wakes up every
        10 minutes, waits until the maintenance trigger time, then marks
        previous unfinished tasks overdue and generates today's tasks
        once per plan (the log is the idempotency token)."""
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        trigger_dt = self.env[
            'sn.wsd.device.maint.generation.log']._parameter_trigger_datetime(now)
        if now < trigger_dt:
            return
        self.env[
            'sn.wsd.device.maint.task']._mark_previous_unfinished_overdue()
        log_model = self.env['sn.wsd.device.maint.generation.log']
        task_model = self.env['sn.wsd.device.maint.task']
        for plan in self.search([('active', '=', True)]):
            already_logged = log_model.search_count([
                ('plan_id', '=', plan.id),
                ('generation_date', '=', today),
            ])
            if already_logged:
                continue
            # Per-equipment due rules apply inside the generation loop
            # (weekly plans may be due for one equipment and not another).
            plan._generate_tasks_for_today(today, now, trigger_dt,
                                           log_model, task_model)

    def _generate_tasks_for_today(self, today, now, trigger_dt,
                                  log_model, task_model):
        self.ensure_one()
        template = self.env['sn.wsd.device.maint.template'].search([
            ('equipment_type_id', '=', self.equipment_type_id.id)])
        items = template.maintenance_item_ids if template else \
            self.env['sn.wsd.device.maint.item']
        today_start = fields.Datetime.to_datetime(today)
        expected = generated = skipped = failed = 0
        errors = []
        equipments = self.env['sn.wsd.device.equipment'].search([
            ('equipment_type_id', '=', self.equipment_type_id.id),
            ('equipment_status', 'in', ['enabled', 'repair']),
        ])
        equipments = equipments.filtered(
            lambda equipment: self._is_equipment_due_today(equipment, today))
        if not equipments:
            return
        # Claim the day with the generation log BEFORE creating tasks: the
        # log is the idempotency token, so writing it first prevents a
        # crashed run from being retried and duplicating tasks.
        log = log_model.create({
            'plan_id': self.id,
            'generation_date': today,
            'trigger_time': f'{trigger_dt.hour:02d}:{trigger_dt.minute:02d}',
            'expected_equipment_count': len(equipments),
            'run_status': 'success',
        })
        for equipment in equipments:
            expected += 1
            try:
                if equipment.last_maintenance_date and \
                        equipment.last_maintenance_date >= today_start:
                    skipped += 1
                    continue
                if not items:
                    failed += 1
                    errors.append(f'{equipment.code}: '
                                  'no maintenance item on the template')
                    continue
                # Supersede stale work: unfinished tasks of previous days
                # for this equipment become overdue before the new task.
                task_model.search([
                    ('equipment_id', '=', equipment.id),
                    ('task_status', 'in', ['pending', 'in_progress']),
                    ('task_date', '<', today),
                ]).write({'task_status': 'overdue'})
                line_vals = [Command.create({
                    'name': item.name,
                    'method': item.method,
                    'guide_file': item.guide_file,
                    'guide_filename': item.guide_filename,
                    'value_type': item.value_type,
                    'upper_limit': item.upper_limit,
                    'lower_limit': item.lower_limit,
                    'unit': item.unit,
                }) for item in items]
                task_model.create({
                    'plan_id': self.id,
                    'equipment_id': equipment.id,
                    'task_date': today,
                    'responsible_user_id': equipment.usage_user_id.id,
                    'line_ids': line_vals,
                })
                generated += 1
            except Exception as exc:  # noqa: BLE001 - logged, not fatal
                failed += 1
                errors.append(f'{equipment.code}: {exc}')
        if failed == 0:
            run_status = 'success'
        elif generated == 0:
            run_status = 'failed'
        else:
            run_status = 'partial'
        log.write({
            'expected_equipment_count': expected,
            'generated_count': generated,
            'skipped_count': skipped,
            'failed_count': failed,
            'run_status': run_status,
            'error_detail': '\n'.join(errors) or False,
            'execution_time': now,
        })
