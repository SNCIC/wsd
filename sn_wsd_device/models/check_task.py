from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CheckTask(models.Model):
    """Spot check task generated from a plan for one equipment."""
    _name = 'sn.wsd.device.check.task'
    _description = 'Equipment Spot Check Task'
    _order = 'task_date desc, id desc'

    name = fields.Char(string='Task Number', default='/', copy=False,
                       readonly=True, index=True)
    plan_id = fields.Many2one(
        'sn.wsd.device.check.plan', string='Check Plan',
        required=True, index=True, ondelete='restrict')
    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment',
        required=True, index=True, ondelete='restrict')
    company_id = fields.Many2one(
        related='equipment_id.company_id', store=True,
        string='Company', index=True)
    equipment_code = fields.Char(
        related='equipment_id.code', store=True, string='Equipment Code')
    equipment_name = fields.Char(
        related='equipment_id.name', store=True, string='Equipment Name')
    equipment_type_code = fields.Char(
        related='plan_id.equipment_type_code', store=True,
        string='Equipment Type Code')
    task_date = fields.Date(
        string='Task Date', required=True, default=fields.Date.context_today,
        index=True)
    task_status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
            ('overdue', 'Overdue'),
        ], string='Task Status', default='pending', required=True,
        index=True, copy=False)
    responsible_user_id = fields.Many2one(
        'res.users', string='Responsible', index=True)
    executor_id = fields.Many2one(
        'res.users', string='Executor', readonly=True, copy=False)
    executed_time = fields.Datetime(
        string='Executed Time', readonly=True, copy=False)
    overall_result = fields.Selection(
        selection=[('pass', 'Pass'), ('fail', 'Fail')],
        string='Overall Result', readonly=True, copy=False, index=True)
    line_ids = fields.One2many(
        'sn.wsd.device.check.task.line', 'task_id', string='Check Lines')
    line_count = fields.Integer(compute='_compute_line_count',
                                string='Line Count')

    def _compute_line_count(self):
        for task in self:
            task.line_count = len(task.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.device.check.task') or '/'
        return super().create(vals_list)

    def action_start(self):
        for task in self:
            if task.task_status in ('pending', 'overdue'):
                task.task_status = 'in_progress'

    def action_submit(self):
        for task in self:
            if task.task_status == 'completed':
                continue
            # Range lines are judged automatically first, then every line
            # must have a result.
            task.line_ids._auto_judge_range_lines()
            missing = task.line_ids.filtered(lambda line: not line.line_result)
            if missing:
                raise UserError(_(
                    'Task %s: items without a result: %s',
                    task.name, ', '.join(missing.mapped('name'))))
            overall = 'pass' if all(
                line.line_result == 'pass' for line in task.line_ids
            ) else 'fail'
            task.write({
                'task_status': 'completed',
                'overall_result': overall,
                'executor_id': self.env.user.id,
                'executed_time': fields.Datetime.now(),
            })
            # Close the loop: feed the equipment ledger.
            task.equipment_id.last_spot_check_date = fields.Datetime.now()

    @api.model
    def _mark_previous_unfinished_overdue(self):
        """Called by the generation cron: tasks from previous days that
        are still uncompleted become overdue once the next tasks are
        being generated."""
        today = fields.Date.context_today(self)
        overdue_tasks = self.search([
            ('task_date', '<', today),
            ('task_status', 'in', ['pending', 'in_progress']),
        ])
        overdue_tasks.write({'task_status': 'overdue'})
        return len(overdue_tasks)


class CheckTaskLine(models.Model):
    """One spot check item of a task, copied from the plan template."""
    _name = 'sn.wsd.device.check.task.line'
    _description = 'Equipment Spot Check Task Line'
    _order = 'sequence, id'
    _rec_name = 'name'

    task_id = fields.Many2one(
        'sn.wsd.device.check.task', string='Check Task',
        required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Item Description', required=True)
    method = fields.Text(string='Maintenance Method')
    guide_file = fields.Binary(string='Guide File', attachment=True)
    guide_filename = fields.Char(string='Guide File Name')
    guide_file_type = fields.Selection(
        selection=[('image', 'Image'), ('video', 'Video')],
        string='Guide File Type', compute='_compute_guide_file_type',
        store=True)
    value_type = fields.Selection(
        selection=[
            ('range', 'Range Value'),
            ('fixed', 'Fixed Value'),
            ('status', 'Status Value'),
        ], string='Value Type', required=True, default='status')
    upper_limit = fields.Float(string='Upper Limit', digits=(12, 4))
    lower_limit = fields.Float(string='Lower Limit', digits=(12, 4))
    unit = fields.Char(string='Unit')
    measured_value = fields.Float(
        string='Measured Value', digits=(12, 4))
    line_result = fields.Selection(
        selection=[('pass', 'Pass'), ('fail', 'Fail')],
        string='Line Result', copy=False)
    line_note = fields.Char(string='Line Note')
    check_photo = fields.Binary(string='Check Photo', attachment=True)

    @api.depends('guide_filename')
    def _compute_guide_file_type(self):
        video_ext = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.wmv')
        for line in self:
            filename = (line.guide_filename or '').lower()
            if filename.endswith(video_ext):
                line.guide_file_type = 'video'
            elif filename:
                line.guide_file_type = 'image'
            else:
                line.guide_file_type = False

    def _auto_judge_range_lines(self):
        """Range lines are judged automatically from the measured value."""
        for line in self.filtered(lambda l: l.value_type == 'range'):
            if line.measured_value or line.measured_value == 0.0:
                line.line_result = (
                    'pass'
                    if line.lower_limit <= line.measured_value <= line.upper_limit
                    else 'fail')

    def action_download_guide(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model=sn.wsd.device.check.task.line'
                   f'&id={self.id}&field=guide_file'
                   f'&filename_field=guide_filename&download=true',
            'target': 'self',
        }
