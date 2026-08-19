from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CalibrationTask(models.Model):
    """Calibration task generated from a per-equipment plan."""
    _name = 'sn.wsd.device.cal.task'
    _description = 'Equipment Calibration Task'
    _order = 'task_date desc, id desc'

    name = fields.Char(string='Task Number', default='/', copy=False,
                       readonly=True, index=True)
    plan_id = fields.Many2one(
        'sn.wsd.device.cal.plan', string='Calibration Plan',
        required=True, index=True, ondelete='restrict')
    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment',
        required=True, index=True, ondelete='restrict')
    equipment_code = fields.Char(
        related='equipment_id.code', store=True, string='Equipment Code')
    equipment_name = fields.Char(
        related='equipment_id.name', store=True, string='Equipment Name')
    equipment_model = fields.Char(
        related='equipment_id.model', store=True, string='Equipment Model')
    is_certified = fields.Boolean(
        related='plan_id.is_certified', store=True,
        string='Certified Calibration')
    is_latest = fields.Boolean(
        string='Is Latest Calibration', copy=False, index=True,
        help='Automatically set on submit: the latest completed task of '
             'this equipment for this certification kind.')
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
        string='Overall Result', copy=False, index=True)
    cert_number = fields.Char(string='Certificate Number', copy=False)
    cert_completion_date = fields.Date(
        string='Certificate Completion Date', copy=False)
    cert_valid_until = fields.Date(
        string='Certificate Valid Until', copy=False)
    cert_file = fields.Binary(
        string='Certificate File', attachment=True, copy=False)
    cert_filename = fields.Char(string='Certificate Filename', copy=False)
    line_ids = fields.One2many(
        'sn.wsd.device.cal.task.line', 'task_id',
        string='Calibration Lines')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.device.cal.task') or '/'
        return super().create(vals_list)

    def action_start(self):
        for task in self:
            if task.task_status in ('pending', 'overdue'):
                task.task_status = 'in_progress'

    def action_submit(self):
        for task in self:
            if task.task_status == 'completed':
                continue
            if not task.overall_result:
                raise UserError(_(
                    'Task %s: the overall result (Pass/Fail) is required.',
                    task.name))
            if task.is_certified:
                missing = []
                if not task.cert_file:
                    missing.append(_('certificate file'))
                if not task.cert_number:
                    missing.append(_('certificate number'))
                if not task.cert_valid_until:
                    missing.append(_('certificate validity date'))
                if missing:
                    raise UserError(_(
                        'Task %s is a certified calibration, missing: %s.',
                        task.name, ', '.join(missing)))
            executed_time = fields.Datetime.now()
            # Latest-calibration flag: one per equipment and certification
            # kind, moved to this task on submit.
            task.search([
                ('equipment_id', '=', task.equipment_id.id),
                ('is_certified', '=', task.is_certified),
                ('is_latest', '=', True),
            ]).write({'is_latest': False})
            task.write({
                'task_status': 'completed',
                'executor_id': self.env.user.id,
                'executed_time': executed_time,
                'is_latest': True,
            })
            # Close the loop: feed the ledger field of this kind.
            equipment = task.equipment_id
            if task.is_certified:
                completion = task.cert_completion_date or executed_time.date()
                equipment.last_external_calibration_date = fields.Datetime.to_datetime(
                    completion)
            else:
                equipment.last_internal_calibration_date = executed_time

    def action_download_certificate(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model=sn.wsd.device.cal.task'
                   f'&id={self.id}&field=cert_file'
                   f'&filename_field=cert_filename&download=true',
            'target': 'self',
        }


class CalibrationTaskLine(models.Model):
    """One calibration record row; values are free text (typed or
    imported from the Excel template)."""
    _name = 'sn.wsd.device.cal.task.line'
    _description = 'Equipment Calibration Task Line'
    _order = 'sequence, id'
    _rec_name = 'item_name'

    task_id = fields.Many2one(
        'sn.wsd.device.cal.task', string='Calibration Task',
        required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    item_name = fields.Char(string='Item Name')
    before_value = fields.Char(string='Before Calibration Value')
    after_value = fields.Char(string='After Calibration Value')
    line_note = fields.Char(string='Line Note')
