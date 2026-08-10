from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    x_failure_code = fields.Char(string='Failure Code', tracking=True)
    x_failure_time = fields.Datetime(string='Failure Time', tracking=True)
    x_impact_level = fields.Selection([
        ('line_stop', 'Line Stop'),
        ('reduced_output', 'Reduced Output'),
        ('no_impact', 'No Impact'),
    ], string='Impact Level', default='no_impact', tracking=True)
    x_urgency = fields.Selection([
        ('urgent', 'Urgent'),
        ('normal', 'Normal'),
        ('low', 'Low'),
    ], string='Urgency', default='normal', tracking=True)
    x_root_cause_code = fields.Char(string='Root Cause Code', tracking=True)
    x_repair_action = fields.Text(string='Repair Action', tracking=True)
    x_repair_start = fields.Datetime(string='Repair Start', tracking=True)
    x_verification_result = fields.Selection([
        ('pending', 'Pending'),
        ('ok', 'OK'),
        ('ng', 'NG'),
    ], string='Verification Result', default='pending', tracking=True, copy=False)
    x_spare_part_note = fields.Text(string='Spare Part Note')
    x_downtime_id = fields.Many2one(
        'sn.wsd.maintenance.downtime',
        string='Downtime Record',
        check_company=True,
        copy=False,
    )

    x_repair_hours = fields.Float(
        string='Repair Hours',
        compute='_compute_x_repair_hours',
        store=True,
    )

    @api.depends('x_repair_start', 'close_date')
    def _compute_x_repair_hours(self):
        for request in self:
            if request.x_repair_start and request.close_date:
                request.x_repair_hours = (request.close_date - request.x_repair_start).total_seconds() / 3600
            else:
                request.x_repair_hours = 0.0

    @api.constrains('x_repair_start', 'close_date')
    def _check_repair_dates(self):
        for request in self:
            if request.x_repair_start and request.close_date and request.x_repair_start > request.close_date:
                raise ValidationError(_('Repair end cannot be earlier than repair start.'))

    @api.onchange('x_verification_result')
    def _onchange_x_verification_result(self):
        for request in self:
            if request.x_verification_result == 'ok':
                done_stage = self.env['maintenance.stage'].search([('done', '=', True)], order='sequence, id', limit=1)
                if done_stage and request.stage_id != done_stage:
                    request.stage_id = done_stage
            elif request.x_verification_result == 'ng':
                request.stage_id = request._get_in_progress_stage()

    def _get_in_progress_stage(self):
        self.ensure_one()
        stages = self.env['maintenance.stage'].search([], order='sequence, id')
        in_progress_stage = stages.filtered(lambda s: not s.done and not s.fold)
        return in_progress_stage[0] if in_progress_stage else stages[0] if stages else False

    def action_wsd_accept_repair(self):
        self.write({
            'x_repair_start': fields.Datetime.now(),
        })
        self.mapped('equipment_id').write({'x_equipment_state': 'repairing'})

    def action_wsd_finish_repair(self):
        for request in self:
            if not request.x_root_cause_code:
                raise UserError(_('Root cause code is required before finishing repair.'))
            if not request.x_repair_action:
                raise UserError(_('Repair action is required before finishing repair.'))
            request.write({
                'close_date': fields.Date.context_today(self),
                'x_verification_result': 'pending',
            })

    def action_wsd_verify_ok(self):
        done_stage = self.env['maintenance.stage'].search([('done', '=', True)], order='sequence, id', limit=1)
        values = {
            'x_verification_result': 'ok',
            'stage_id': done_stage.id if done_stage else request.stage_id.id,
        }
        self.write(values)
        for request in self:
            request.equipment_id.write({'x_equipment_state': 'running'})
            request.equipment_id._create_lifecycle_log(
                'repair',
                _('Repair request %s verified OK.') % request.display_name,
                source_model=request._name,
                source_id=request.id,
            )
            if request.x_downtime_id and request.x_downtime_id.state == 'open':
                request.x_downtime_id.action_close()

    def action_wsd_verify_ng(self):
        self.write({
            'x_verification_result': 'ng',
            'close_date': False,
        })
        self.mapped('equipment_id').write({'x_equipment_state': 'repairing'})

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        for request in requests.filtered(lambda item: item.maintenance_type == 'corrective' and item.equipment_id):
            if request.x_failure_code:
                request.equipment_id.write({'x_equipment_state': 'repairing'})
            if not request.x_downtime_id and request.x_impact_level in ('line_stop', 'reduced_output'):
                request.x_downtime_id = self.env['sn.wsd.maintenance.downtime'].create({
                    'equipment_id': request.equipment_id.id,
                    'workcenter_id': request.equipment_id.x_mes_workcenter_id.id,
                    'reason': request.name,
                    'failure_code': request.x_failure_code,
                    'maintenance_request_id': request.id,
                })
        return requests
