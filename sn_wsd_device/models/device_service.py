from datetime import datetime, time

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# PDA-facing task kinds -> task models. The front end never passes a model
# name, only these short codes.
TASK_KINDS = {
    'check': 'sn.wsd.device.check.task',
    'maint': 'sn.wsd.device.maint.task',
}

# Same eligibility rule as the generation cron: only in-use or under-repair
# equipment can be checked / maintained / reported.
ELIGIBLE_STATUSES = ('enabled', 'repair')

OPEN_STATUSES = ('pending', 'in_progress', 'overdue')

FAULT_TYPES = ('mechanical', 'electrical', 'software', 'other')
FAULT_LEVELS = ('minor', 'general', 'critical')


class SnDeviceService(models.AbstractModel):
    """PDA service layer for equipment management.

    Every method shares the model methods used by the PC buttons
    (action_start / action_submit), so guards and state transitions stay
    identical on both sides.
    """

    _name = 'sn.device.service'
    _description = 'Device PDA Service'

    # ===== helpers =====

    @api.model
    def _task_model(self, kind):
        model_name = TASK_KINDS.get(kind)
        if not model_name:
            raise UserError(_('Unknown task kind %s.', kind))
        return self.env[model_name]

    @api.model
    def _resolve_equipment(self, code):
        code = (code or '').strip()
        equipment = self.env['sn.wsd.device.equipment'].search(
            [('code', '=', code),
             ('company_id', '=', self.env.company.id)], limit=1)
        if not equipment:
            raise UserError(_('Equipment %s does not exist.', code))
        return equipment

    @api.model
    def _resolve_task(self, kind, task_id):
        task = self._task_model(kind).browse(task_id).exists()
        if not task:
            raise UserError(_('Task not found.'))
        if task.company_id != self.env.company:
            raise UserError(_('Task not found.'))
        return task

    @api.model
    def _check_executable(self, equipment):
        if equipment.equipment_status not in ELIGIBLE_STATUSES:
            raise UserError(_(
                'Equipment %s is %s: check / maintenance tasks cannot be '
                'executed.', equipment.code, equipment.equipment_status))

    @api.model
    def _equipment_card(self, equipment):
        return {
            'id': equipment.id,
            'code': equipment.code,
            'name': equipment.name,
            'model': equipment.model or '',
            'status': equipment.equipment_status,
            'location': equipment.location_id.complete_name or '',
            'last_spot_check': (
                fields.Datetime.to_string(equipment.last_spot_check_date)
                if equipment.last_spot_check_date else ''),
            'last_maintenance': (
                fields.Datetime.to_string(equipment.last_maintenance_date)
                if equipment.last_maintenance_date else ''),
            'maintenance_user': equipment.maintenance_user_id.name or '',
        }

    @api.model
    def _task_payload(self, kind, task):
        return {
            'kind': kind,
            'id': task.id,
            'name': task.name,
            'status': task.task_status,
            'task_date': fields.Date.to_string(task.task_date),
            'item_count': len(task.line_ids),
            'overall_result': task.overall_result or '',
        }

    @api.model
    def _line_payload(self, line):
        return {
            'id': line.id,
            'name': line.name,
            'method': line.method or '',
            'value_type': line.value_type,
            'lower_limit': line.lower_limit,
            'upper_limit': line.upper_limit,
            'unit': line.unit or '',
            'measured_value': line.measured_value,
            'line_result': line.line_result or '',
            'line_note': line.line_note or '',
            'has_guide': bool(line.guide_filename),
        }

    @api.model
    def _task_lines(self, kind, task_id):
        task = self._resolve_task(kind, task_id)
        return {
            'task': self._task_payload(kind, task),
            'equipment': self._equipment_card(task.equipment_id),
            'lines': [self._line_payload(line)
                      for line in task.line_ids.sorted(
                          key=lambda l: (l.sequence, l.id))],
        }

    @api.model
    def _open_tasks_of_equipment(self, equipment):
        """Open (pending / in_progress / overdue) tasks, both kinds."""
        tasks = []
        for kind, model_name in TASK_KINDS.items():
            found = self.env[model_name].search([
                ('equipment_id', '=', equipment.id),
                ('company_id', '=', self.env.company.id),
                ('task_status', 'in', list(OPEN_STATUSES)),
            ], order='task_date, id')
            tasks += [(kind, task) for task in found]
        return tasks

    # ===== board =====

    @api.model
    def locations(self):
        """Location tree for the PDA filter selector: own name + depth for
        indentation, full path for the context bar label."""
        result = []
        for location in self.env['sn.wsd.device.location'].search(
                [], order='parent_path, id'):
            depth = max((location.parent_path or '').count('/') - 1, 0)
            result.append({
                'id': location.id,
                'name': location.name,
                'full_name': location.complete_name,
                'depth': depth,
            })
        return result

    @api.model
    def today_board(self, location_id=None):
        """Cross-equipment board: open tasks grouped by equipment plus the
        tasks already executed today, with progress counters."""
        today = fields.Date.today()
        day_start = datetime.combine(today, time.min)
        base_domain = [('company_id', '=', self.env.company.id)]
        if location_id:
            base_domain.append(
                ('equipment_id.location_id', 'child_of', int(location_id)))

        open_tasks, done_tasks = [], []
        for kind, model_name in TASK_KINDS.items():
            model = self.env[model_name]
            found = model.search(base_domain + [
                ('task_date', '<=', today),
                ('task_status', 'in', list(OPEN_STATUSES)),
            ], order='task_date, id')
            open_tasks += [(kind, task) for task in found]
            found = model.search(base_domain + [
                ('task_status', '=', 'completed'),
                ('executed_time', '>=', day_start),
            ], order='executed_time desc, id desc')
            done_tasks += [(kind, task) for task in found]

        grouped = {}
        for kind, task in open_tasks:
            grouped.setdefault(task.equipment_id, []).append((kind, task))
        groups = []
        for equipment in sorted(grouped, key=lambda e: (e.code or '', e.id)):
            groups.append({
                'equipment': self._equipment_card(equipment),
                'tasks': [self._task_payload(kind, task)
                          for kind, task in grouped[equipment]],
            })

        return {
            'progress': {
                'due': len(open_tasks) + len(done_tasks),
                'done': len(done_tasks),
                'todo': len(open_tasks),
                'overdue': sum(
                    1 for _, task in open_tasks
                    if task.task_status == 'overdue'),
            },
            'groups': groups,
            'done': [
                dict(self._task_payload(kind, task),
                     executed_time=fields.Datetime.to_string(
                         task.executed_time))
                for kind, task in done_tasks],
        }

    # ===== scan / task execution =====

    @api.model
    def resolve(self, code):
        equipment = self._resolve_equipment(code)
        tasks = self._open_tasks_of_equipment(equipment)
        return {
            'equipment': self._equipment_card(equipment),
            'tasks': [self._task_payload(kind, task) for kind, task in tasks],
        }

    @api.model
    def task_start(self, kind, task_id):
        task = self._resolve_task(kind, task_id)
        self._check_executable(task.equipment_id)
        if task.task_status == 'completed':
            raise UserError(_('Task %s is already completed.', task.name))
        if task.task_status in ('pending', 'overdue'):
            # Prefill "everything OK" so the worker only touches abnormal
            # items: status/fixed items get pass, range items get the
            # mid-range value (kept and re-judged at submit).
            for line in task.line_ids:
                if line.value_type == 'range':
                    if not line.measured_value:
                        line.measured_value = (
                            line.lower_limit + line.upper_limit) / 2.0
                elif not line.line_result:
                    line.line_result = 'pass'
            task.action_start()
        return self._task_lines(kind, task_id)

    @api.model
    def task_detail(self, kind, task_id):
        return self._task_lines(kind, task_id)

    @api.model
    def task_update_line(self, kind, line_id, measured_value=None,
                         line_result=None, line_note=None):
        # Resolve the line through the task model so the relation name is
        # derived server-side, never trusted from the front end.
        relation = self._task_model(kind)._fields['line_ids'].comodel_name
        line = self.env[relation].browse(line_id).exists()
        if not line or not line.task_id \
                or line.task_id.company_id != self.env.company:
            raise UserError(_('Item not found.'))
        task = self._resolve_task(kind, line.task_id.id)
        if task.task_status != 'in_progress':
            raise UserError(_(
                'Task %s is not in progress: start it first.', task.name))
        vals = {}
        if measured_value is not None:
            vals['measured_value'] = measured_value
        if line_result:
            vals['line_result'] = line_result
        if line_note is not None:
            vals['line_note'] = line_note
        if vals:
            line.write(vals)
            # Immediate feedback for range items, same rule as submit.
            if 'measured_value' in vals:
                line._auto_judge_range_lines()
        return self._line_payload(line)

    @api.model
    def task_submit(self, kind, task_id):
        task = self._resolve_task(kind, task_id)
        self._check_executable(task.equipment_id)
        task.action_submit()
        return {
            'name': task.name,
            'overall_result': task.overall_result,
        }

    # ===== repair report =====

    @api.model
    def repair_create(self, code, fault_type, fault_level, description):
        equipment = self._resolve_equipment(code)
        self._check_executable(equipment)
        description = (description or '').strip()
        if not description:
            raise UserError(_('Fault description is required.'))
        if fault_type not in FAULT_TYPES:
            raise UserError(_('Unknown fault type.'))
        if fault_level not in FAULT_LEVELS:
            raise UserError(_('Unknown fault level.'))
        phenomenon = '<p>%s</p>' % str(escape(description)).replace(
            '\n', '<br/>')
        initial_handling = '<p>%s</p>' % _(
            'Pending initial handling (reported from PDA).')
        order = self.env['sn.wsd.device.repair.order'].create({
            'equipment_id': equipment.id,
            'fault_phenomenon': phenomenon,
            'initial_handling': initial_handling,
            'fault_type': fault_type,
            'fault_level': fault_level,
            'responsible_user_id': equipment.maintenance_user_id.id,
            'reported_user_id': self.env.user.id,
        })
        return {'order': order.name, 'equipment': equipment.code}
