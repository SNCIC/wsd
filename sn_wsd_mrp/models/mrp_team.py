from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_is_zero


class SnMrpTeam(models.Model):
    _name = 'sn.mrp.team'
    _description = 'Manufacturing Team'
    _order = 'production_line_id, sequence, code, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [('active', 'In Use'), ('inactive', 'Inactive')],
        default='active',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        required=True,
        check_company=True,
        ondelete='restrict',
    )
    production_line_id = fields.Many2one(
        'sn.mrp.production.line',
        string='Production Line',
        required=True,
        check_company=True,
        ondelete='restrict',
    )
    shift_id = fields.Many2one(
        'resource.calendar',
        string='Shift',
        check_company=True,
    )
    member_ids = fields.One2many(
        'sn.mrp.team.member',
        'team_id',
        string='Members',
        copy=True,
    )
    member_count = fields.Integer(compute='_compute_member_count')
    leader_member_id = fields.Many2one(
        'sn.mrp.team.member',
        string='Team Leader',
        compute='_compute_leader_member_id',
        store=True,
    )
    performance_ratio_total = fields.Float(
        string='Performance Ratio Total',
        compute='_compute_performance_ratio_total',
        store=True,
    )
    note = fields.Text()

    _sn_mrp_team_company_code_unique = models.Constraint(
        'unique(company_id, code)',
        'The team code must be unique per company.',
    )

    @api.depends('member_ids')
    def _compute_member_count(self):
        for record in self:
            record.member_count = len(record.member_ids)

    @api.depends('member_ids.is_leader')
    def _compute_leader_member_id(self):
        for record in self:
            record.leader_member_id = record.member_ids.filtered('is_leader')[:1]

    @api.depends('member_ids.performance_ratio')
    def _compute_performance_ratio_total(self):
        for record in self:
            record.performance_ratio_total = sum(record.member_ids.mapped('performance_ratio'))

    @api.onchange('member_ids')
    def _onchange_member_ids_rebalance_ratio(self):
        """成员增删或改某行 ratio 时，重分配 performance_ratio。
        """
        for team in self:
            members = team.member_ids
            if not members:
                continue
            edited = members.filtered(
                lambda m: m._origin and not float_is_zero(
                    m.performance_ratio - m._origin.performance_ratio,
                    precision_rounding=0.0001,
                )
            )[:1]
            members._rebalance_performance_ratio(edited_member=edited or None)

    @api.constrains('workshop_id', 'production_line_id')
    def _check_workshop_matches_production_line(self):
        for record in self:
            if record.production_line_id and record.production_line_id.workshop_id != record.workshop_id:
                raise ValidationError(_('The production line must belong to the selected workshop.'))

    @api.constrains('member_ids', 'member_ids.is_leader')
    def _check_leader_count(self):
        for record in self:
            leader_count = len(record.member_ids.filtered('is_leader'))
            if leader_count > 1:
                raise ValidationError(_('A team can only have one team leader.'))

    @api.constrains('member_ids', 'member_ids.performance_ratio')
    def _check_performance_ratio_total(self):
        for record in self:
            if record.member_ids and not float_is_zero(record.performance_ratio_total - 100.0, precision_rounding=0.0100):
                raise ValidationError(_('The total performance ratio of team members must be 100%.'))

    @api.onchange('workshop_id')
    def _onchange_workshop_id_sync_company(self):
        for record in self:
            if record.workshop_id:
                record.company_id = record.workshop_id.company_id
                if record.production_line_id and record.production_line_id.workshop_id != record.workshop_id:
                    record.production_line_id = False

    @api.onchange('production_line_id')
    def _onchange_production_line_id_sync_workshop(self):
        for record in self:
            if record.production_line_id:
                record.workshop_id = record.production_line_id.workshop_id
                record.company_id = record.production_line_id.company_id

    def action_set_active(self):
        self.write({'state': 'active', 'active': True})

    def action_set_inactive(self):
        self.write({'state': 'inactive', 'active': False})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('active') is False and not vals.get('state'):
                vals['state'] = 'inactive'
            elif vals.get('state') == 'inactive' and 'active' not in vals:
                vals['active'] = False
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if vals.get('active') is False and 'state' not in vals:
            vals['state'] = 'inactive'
        elif vals.get('active') is True and 'state' not in vals:
            vals['state'] = 'active'
        elif vals.get('state') == 'inactive' and 'active' not in vals:
            vals['active'] = False
        elif vals.get('state') == 'active' and 'active' not in vals:
            vals['active'] = True
        return super().write(vals)

    def _get_copy_code(self):
        self.ensure_one()
        base_code = f'{self.code}_COPY'
        code = base_code
        index = 1
        while self.search_count([
            ('company_id', '=', self.company_id.id),
            ('code', '=', code),
        ]):
            index += 1
            code = f'{base_code}{index}'
        return code

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault('name', _('%s (Copy)') % self.name)
        default.setdefault('code', self._get_copy_code())
        default.setdefault('state', 'active')
        default.setdefault('active', True)
        return super().copy(default=default)

    def action_open_add_members_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add Team Members'),
            'res_model': 'sn.mrp.team.member.add.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_team_id': self.id},
        }

    def action_open_remove_members_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remove Team Members'),
            'res_model': 'sn.mrp.team.member.remove.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_team_id': self.id},
        }


class SnMrpTeamMember(models.Model):
    _name = 'sn.mrp.team.member'
    _description = 'Manufacturing Team Member'
    _order = 'team_id, sequence, employee_code, id'
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    team_id = fields.Many2one(
        'sn.mrp.team',
        required=True,
        check_company=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        related='team_id.company_id',
        store=True,
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        check_company=True,
        ondelete='restrict',
    )
    employee_code = fields.Char(string='Employee Code', required=True)
    performance_ratio = fields.Float(required=True, default=0.0)
    is_leader = fields.Boolean(string='Team Leader')
    workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        related='team_id.workshop_id',
        store=True,
    )
    production_line_id = fields.Many2one(
        'sn.mrp.production.line',
        related='team_id.production_line_id',
        store=True,
    )
    shift_id = fields.Many2one(
        'resource.calendar',
        related='team_id.shift_id',
        store=True,
    )

    _sn_mrp_team_member_unique = models.Constraint(
        'unique(team_id, employee_id)',
        'The employee is already a member of this team.',
    )
    _sn_mrp_team_member_ratio_check = models.Constraint(
        'CHECK(performance_ratio >= 0 AND performance_ratio <= 100)',
        'The performance ratio must be between 0 and 100.',
    )

    @api.onchange('employee_id')
    def _onchange_employee_id_sync_employee_code(self):
        for record in self:
            if record.employee_id and not record.employee_code:
                record.employee_code = record.employee_id.barcode or record.employee_id.pin or record.employee_id.name

    def _rebalance_performance_ratio(self, edited_member=None):
        """把 100% 在本集合的成员间分配。

        :param edited_member: 被用户手动修改的成员记录（保留其值），其余成员均摊剩余。
            若为 None，则所有成员均摊（新增行/初始化场景）。
        """
        all_members = self
        if not all_members:
            return
        if len(all_members) == 1:
            all_members.performance_ratio = 100.0
            return
        if edited_member and edited_member in all_members:
            edited_val = edited_member.performance_ratio
            if edited_val > 100.0:
                raise ValidationError(_('Performance ratio cannot exceed 100%.'))
            remaining = max(0.0, 100.0 - edited_val)
            others = all_members - edited_member
            share = remaining / len(others)
            for m in others:
                m.performance_ratio = round(share, 4)
        else:
            share = 100.0 / len(all_members)
            for m in all_members:
                m.performance_ratio = round(share, 4)

    @api.constrains('employee_code')
    def _check_employee_code(self):
        for record in self:
            if not record.employee_code:
                raise ValidationError(_('Employee code is required.'))

    def unlink(self):
        for record in self:
            if record.is_leader:
                raise ValidationError(_('You must assign a new team leader before removing the current team leader.'))
        return super().unlink()
