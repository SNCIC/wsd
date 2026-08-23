from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SnWsdSkipRequest(models.Model):
    _name = 'sn.wsd.skip.request'
    _description = 'WSD Skip Station Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Request No.', default=lambda self: _('New'), readonly=True, copy=False, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company, index=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True, check_company=True, index=True, tracking=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='production_id.x_mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    product_id = fields.Many2one(related='production_id.product_id', store=True, readonly=True)
    route_id = fields.Many2one(related='production_id.x_route_id', store=True, readonly=True)
    applicant_id = fields.Many2one('res.users', string='Applicant', required=True, default=lambda self: self.env.user, tracking=True)
    request_date = fields.Datetime(string='Request Time', required=True, default=fields.Datetime.now, tracking=True)
    reason = fields.Text(string='Reason', required=True, tracking=True)
    line_ids = fields.One2many('sn.wsd.skip.request.line', 'request_id', string='Skip Operations', copy=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('revoked', 'Revoked'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        required=True,
        default='draft',
        tracking=True,
        index=True,
        copy=False,
    )
    submitted_at = fields.Datetime(string='Submitted At', readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False, tracking=True)
    approved_at = fields.Datetime(string='Approved At', readonly=True, copy=False, tracking=True)
    rejected_by_id = fields.Many2one('res.users', string='Rejected By', readonly=True, copy=False)
    rejected_at = fields.Datetime(string='Rejected At', readonly=True, copy=False)
    reject_reason = fields.Text(string='Reject Reason', copy=False)
    revoked_by_id = fields.Many2one('res.users', string='Revoked By', readonly=True, copy=False)
    revoked_at = fields.Datetime(string='Revoked At', readonly=True, copy=False)
    revoke_reason = fields.Text(string='Revoke Reason', copy=False)
    line_count = fields.Integer(string='Operation Count', compute='_compute_line_count')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for request in self:
            request.line_count = len(request.line_ids)

    @api.onchange('production_id')
    def _onchange_production_id(self):
        for request in self:
            if request.production_id:
                request.company_id = request.production_id.company_id
            request.line_ids = [fields.Command.clear()]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.skip.request') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        protected_fields = {
            'production_id',
            'applicant_id',
            'request_date',
            'reason',
            'line_ids',
            'company_id',
        }
        if protected_fields.intersection(vals):
            for request in self:
                if request.state not in ('draft',):
                    raise UserError(_('Only draft skip requests can be edited.'))
        return super().write(vals)

    def unlink(self):
        for request in self:
            if request.state not in ('draft', 'cancelled'):
                raise UserError(_('Only draft or cancelled skip requests can be deleted.'))
        return super().unlink()

    def _check_user_can_approve(self):
        if not self.env.user.has_group('mrp.group_mrp_manager'):
            raise UserError(_('Only manufacturing administrators can perform this action.'))

    def _check_has_lines(self):
        for request in self:
            if not request.line_ids:
                raise UserError(_('At least one operation must be selected.'))

    def _check_lines_not_processed(self):
        for request in self:
            for line in request.line_ids:
                line._check_not_processed()

    def _check_no_active_duplicate(self):
        line_model = self.env['sn.wsd.skip.request.line']
        for request in self:
            for line in request.line_ids:
                scope_domain = [('request_id.mes_order_id', '=', request.mes_order_id.id)]
                duplicate = line_model.search([
                    ('id', '!=', line.id),
                    ('route_operation_id', '=', line.route_operation_id.id),
                    ('request_id.state', '=', 'approved'),
                ] + scope_domain, limit=1)
                if duplicate:
                    raise UserError(_(
                        'Operation %(operation)s already has an approved skip request for this MES order.',
                        operation=line.route_operation_id.display_name,
                    ))

    def _refresh_related_wip(self):
        productions = self.mapped('production_id')
        route_operations = productions.mapped('x_mes_order_id.x_route_operation_ids')
        if route_operations:
            route_operations._compute_qty_ready()
            route_operations._compute_state()
        if productions and hasattr(productions, 'action_refresh_wip_snapshot'):
            productions.action_refresh_wip_snapshot()

    def action_submit(self):
        for request in self:
            if request.state != 'draft':
                raise UserError(_('Only draft skip requests can be submitted.'))
        self._check_has_lines()
        self._check_lines_not_processed()
        self._check_no_active_duplicate()
        self.write({'state': 'submitted', 'submitted_at': fields.Datetime.now()})
        return True

    def action_approve(self):
        self._check_user_can_approve()
        for request in self:
            if request.state != 'submitted':
                raise UserError(_('Only submitted skip requests can be approved.'))
        self._check_has_lines()
        self._check_lines_not_processed()
        self._check_no_active_duplicate()
        self.write({
            'state': 'approved',
            'approved_by_id': self.env.user.id,
            'approved_at': fields.Datetime.now(),
        })
        self._refresh_related_wip()
        return True

    def action_reject(self):
        self._check_user_can_approve()
        for request in self:
            if request.state != 'submitted':
                raise UserError(_('Only submitted skip requests can be rejected.'))
        self.write({
            'state': 'rejected',
            'rejected_by_id': self.env.user.id,
            'rejected_at': fields.Datetime.now(),
        })
        return True

    def action_revoke(self):
        self._check_user_can_approve()
        for request in self:
            if request.state != 'approved':
                raise UserError(_('Only approved skip requests can be revoked.'))
        self._check_lines_not_processed()
        self.write({
            'state': 'revoked',
            'revoked_by_id': self.env.user.id,
            'revoked_at': fields.Datetime.now(),
        })
        self._refresh_related_wip()
        return True

    def action_cancel(self):
        for request in self:
            if request.state not in ('draft', 'submitted'):
                raise UserError(_('Only draft or submitted skip requests can be cancelled.'))
        self.write({'state': 'cancelled'})
        return True


class SnWsdSkipRequestLine(models.Model):
    _name = 'sn.wsd.skip.request.line'
    _description = 'WSD Skip Station Request Line'
    _order = 'sequence, id'
    _check_company_auto = True

    request_id = fields.Many2one(
        'sn.wsd.skip.request',
        string='Skip Request',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(related='request_id.company_id', store=True, readonly=True)
    production_id = fields.Many2one(related='request_id.production_id', store=True, readonly=True, index=True)
    mes_order_id = fields.Many2one(related='request_id.mes_order_id', store=True, readonly=True, index=True)
    route_id = fields.Many2one(related='request_id.route_id', store=True, readonly=True)
    sequence = fields.Integer(default=10)
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Operation',
        required=True,
        check_company=True,
        index=True,
        domain="[('mes_order_id', '=', mes_order_id)]",
    )
    workcenter_id = fields.Many2one(related='route_operation_id.workcenter_id', store=True, readonly=True)
    operation_code = fields.Char(related='route_operation_id.x_step_code', store=True, readonly=True)
    state = fields.Selection(related='request_id.state', store=True, readonly=True, index=True)
    is_processed = fields.Boolean(string='Processed', compute='_compute_is_processed')
    note = fields.Char(string='Notes')

    _request_route_operation_uniq = models.Constraint(
        'unique(request_id, route_operation_id)',
        'The operation must be unique within one skip request.',
    )

    @api.depends('route_operation_id')
    def _compute_is_processed(self):
        for line in self:
            line.is_processed = line._is_route_operation_processed()

    @api.onchange('route_operation_id')
    def _onchange_route_operation_id(self):
        for line in self:
            if line.route_operation_id:
                line.sequence = line.route_operation_id.sequence

    @api.constrains('request_id', 'route_operation_id')
    def _check_route_operation_scope(self):
        for line in self:
            if line.route_operation_id.mes_order_id != line.request_id.mes_order_id:
                raise ValidationError(_('The skipped operation must belong to the selected manufacturing order.'))

    def _is_route_operation_processed(self):
        self.ensure_one()
        if not self.route_operation_id:
            return False
        History = self.env['sn.wsd.serial.operation.history']
        Report = self.env['sn.wsd.mes.operation.report']
        return bool(
            History.search_count([('route_operation_id', '=', self.route_operation_id.id)])
            or Report.search_count([('route_operation_id', '=', self.route_operation_id.id)])
        )

    def _check_not_processed(self):
        self.ensure_one()
        if self._is_route_operation_processed():
            raise UserError(_('This operation has already been processed and cannot be skipped.'))

    @api.model
    def get_approved_skip_route_operations(self, mes_order, route_operations=False):
        if not mes_order:
            return self.env['sn.wsd.mes.order.route.operation']
        domain = [('request_id.state', '=', 'approved')]
        domain.append(('request_id.mes_order_id', '=', mes_order.id))
        if route_operations:
            domain.append(('route_operation_id', 'in', route_operations.ids))
        return self.search(domain).mapped('route_operation_id')
