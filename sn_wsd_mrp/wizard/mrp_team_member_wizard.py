from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SnMrpTeamMemberAddWizard(models.TransientModel):
    _name = 'sn.mrp.team.member.add.wizard'
    _description = 'Add Manufacturing Team Members Wizard'

    team_id = fields.Many2one('sn.mrp.team', required=True)
    company_id = fields.Many2one(
        'res.company',
        related='team_id.company_id',
        readonly=True,
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        domain="[('company_id', '=', company_id)]",
        required=True,
    )

    def action_confirm(self):
        self.ensure_one()
        invalid_employees = self.employee_ids.filtered(lambda employee: employee.company_id != self.company_id)
        if invalid_employees:
            raise ValidationError(_('All employees must belong to the team company.'))
        existing_employee_ids = set(self.team_id.member_ids.mapped('employee_id').ids)
        for employee in self.employee_ids:
            if employee.id in existing_employee_ids:
                continue
            self.env['sn.mrp.team.member'].create({
                'team_id': self.team_id.id,
                'employee_id': employee.id,
                'employee_code': employee.barcode or employee.pin or employee.name,
                'performance_ratio': 0.0,
            })
        return {'type': 'ir.actions.act_window_close'}


class SnMrpTeamMemberRemoveWizard(models.TransientModel):
    _name = 'sn.mrp.team.member.remove.wizard'
    _description = 'Remove Manufacturing Team Members Wizard'

    team_id = fields.Many2one('sn.mrp.team', required=True)
    member_ids = fields.Many2many(
        'sn.mrp.team.member',
        string='Members',
        domain="[('team_id', '=', team_id)]",
        required=True,
    )
    new_leader_member_id = fields.Many2one(
        'sn.mrp.team.member',
        string='New Team Leader',
        domain="[('team_id', '=', team_id)]",
    )
    leader_reassignment_required = fields.Boolean(
        compute='_compute_leader_reassignment_required',
    )

    @api.depends('member_ids')
    def _compute_leader_reassignment_required(self):
        for wizard in self:
            wizard.leader_reassignment_required = any(wizard.member_ids.mapped('is_leader'))

    def action_confirm(self):
        self.ensure_one()
        leader_to_remove = self.member_ids.filtered('is_leader')
        if leader_to_remove:
            if not self.new_leader_member_id:
                raise ValidationError(_('You must choose a new team leader before removing the current team leader.'))
            if self.new_leader_member_id in self.member_ids:
                raise ValidationError(_('The new team leader cannot be part of the members being removed.'))
            self.new_leader_member_id.is_leader = True
        self.member_ids.unlink()
        return {'type': 'ir.actions.act_window_close'}
