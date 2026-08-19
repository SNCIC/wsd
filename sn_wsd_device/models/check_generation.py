from odoo import api, fields, models


class CheckGenerationLog(models.Model):
    """Audit trail of one plan run of the shared generation cron."""
    _name = 'sn.wsd.device.check.generation.log'
    _description = 'Spot Check Generation Log'
    _order = 'id desc'

    plan_id = fields.Many2one(
        'sn.wsd.device.check.plan', string='Check Plan',
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

    # The generation cron itself lives on the plan model.
    @api.model
    def _parameter_trigger_datetime(self, now):
        """Parse the global trigger time parameter into today's datetime."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'equipment_inspection_trigger_time', '08:00')
        try:
            hour_str, minute_str = raw.strip().split(':')
            hour, minute = int(hour_str), int(minute_str)
            assert 0 <= hour <= 23 and 0 <= minute <= 59
        except (ValueError, AssertionError):
            hour, minute = 8, 0
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


class CheckPlan(models.Model):
    """Add the shared cron entry point to the plan model."""

    _inherit = 'sn.wsd.device.check.plan'

    @api.model
    def _cron_generate_check_tasks(self):
        """Single shared cron for every plan.

        Wakes up hourly, waits until the global trigger time, then
        generates today's tasks for every due plan exactly once (the
        generation log is the idempotency token: one log per plan+date).
        """
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        trigger_dt = self.env[
            'sn.wsd.device.check.generation.log']._parameter_trigger_datetime(now)
        if now < trigger_dt:
            return
        # Overdue rule: when the next generation starts, any uncompleted
        # task from a previous day becomes overdue.
        self.env['sn.wsd.device.check.task']._mark_previous_unfinished_overdue()
        log_model = self.env['sn.wsd.device.check.generation.log']
        task_model = self.env['sn.wsd.device.check.task']
        for plan in self.search([('active', '=', True)]):
            already_logged = log_model.search_count([
                ('plan_id', '=', plan.id),
                ('generation_date', '=', today),
            ])
            if already_logged:
                continue
            if not plan._is_due_today(today):
                continue
            plan._generate_tasks_for_today(today, now, trigger_dt,
                                           log_model, task_model)

    def _generate_tasks_for_today(self, today, now, trigger_dt,
                                  log_model, task_model):
        self.ensure_one()
        template = self.env['sn.wsd.device.maint.template'].search([
            ('equipment_type_id', '=', self.equipment_type_id.id)])
        spot_items = template.spot_check_item_ids if template else \
            self.env['sn.wsd.device.maint.item']
        today_start = fields.Datetime.to_datetime(today)
        expected = generated = skipped = failed = 0
        errors = []
        equipments = self.env['sn.wsd.device.equipment'].search([
            ('equipment_type_id', '=', self.equipment_type_id.id),
            ('equipment_status', 'in', ['enabled', 'repair']),
        ])
        for equipment in equipments:
            expected += 1
            try:
                if equipment.last_spot_check_date and \
                        equipment.last_spot_check_date >= today_start:
                    skipped += 1
                    continue
                duplicate = task_model.search_count([
                    ('equipment_id', '=', equipment.id),
                    ('task_date', '=', today),
                ])
                if duplicate:
                    skipped += 1
                    continue
                if not spot_items:
                    failed += 1
                    errors.append(_mark_error(
                        equipment.code, 'no spot check item on the template'))
                    continue
                line_vals = [(0, 0, {
                    'name': item.name,
                    'method': item.method,
                    'guide_file': item.guide_file,
                    'guide_filename': item.guide_filename,
                    'value_type': item.value_type,
                    'upper_limit': item.upper_limit,
                    'lower_limit': item.lower_limit,
                    'unit': item.unit,
                }) for item in spot_items]
                task_model.create({
                    'plan_id': self.id,
                    'equipment_id': equipment.id,
                    'task_date': today,
                    'responsible_user_id': equipment.usage_user_id.id,
                } | {'line_ids': line_vals})
                generated += 1
            except Exception as exc:  # noqa: BLE001 - logged, not fatal
                failed += 1
                errors.append(_mark_error(equipment.code, str(exc)))
        if failed == 0:
            run_status = 'success'
        elif generated == 0:
            run_status = 'failed'
        else:
            run_status = 'partial'
        log_model.create({
            'plan_id': self.id,
            'generation_date': today,
            'trigger_time': f'{trigger_dt.hour:02d}:{trigger_dt.minute:02d}',
            'expected_equipment_count': expected,
            'generated_count': generated,
            'skipped_count': skipped,
            'failed_count': failed,
            'run_status': run_status,
            'error_detail': '\n'.join(errors) or False,
            'execution_time': now,
        })


def _mark_error(equipment_code, message):
    return f'{equipment_code}: {message}'
