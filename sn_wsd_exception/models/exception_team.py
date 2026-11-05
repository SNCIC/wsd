from odoo import fields, models


class SnWsdExceptionTeam(models.Model):
    _name = 'sn.wsd.exception.team'
    _description = 'SN WSD Exception Responsible Team'
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(string='Team', required=True, translate=True)
    code = fields.Char(string='Code', index=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    member_ids = fields.Many2many(
        'res.users',
        'sn_wsd_exception_team_user_rel',
        'team_id',
        'user_id',
        string='Members',
        help='Users notified when a ticket is routed to this team. Whoever is on shift claims the ticket.',
    )
    leader_id = fields.Many2one('res.users', string='Team Leader')
    ticket_count = fields.Integer(compute='_compute_ticket_count')

    _name_company_uniq = models.Constraint(
        'unique(company_id, name)',
        'The responsible team name must be unique per company.',
    )

    def _compute_ticket_count(self):
        groups = self.env['sn.wsd.exception.ticket']._read_group(
            [('team_id', 'in', self.ids)], ['team_id'], ['__count'],
        )
        counts = {team.id: count for team, count in groups}
        for team in self:
            team.ticket_count = counts.get(team.id, 0)
