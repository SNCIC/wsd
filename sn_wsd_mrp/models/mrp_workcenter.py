from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    x_workcenter_type = fields.Selection(
        [
            ('workshop', 'Workshop Level'),
            ('line', 'Production Line Level'),
        ],
        string='Ownership Type',
        compute='_compute_x_workcenter_type',
        store=True,
    )
    x_workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        check_company=True,
        tracking=True,
    )
    x_production_line_id = fields.Many2one(
        'sn.mrp.production.line',
        string='Production Line',
        check_company=True,
        tracking=True,
    )
    x_workcenter_status = fields.Selection(
        [
            ('active', 'Active'),
            ('inactive', 'Inactive'),
        ],
        string='Status',
        compute='_compute_x_workcenter_status',
        inverse='_inverse_x_workcenter_status',
        search='_search_x_workcenter_status',
    )
    x_operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='Operation',
        check_company=True,
        domain="[('company_id', '=', company_id)]",
        help='Operation that can be executed at this work center.',
    )

    _sn_wsd_workcenter_code_unique = models.Constraint(
        'unique(code)',
        'The work center code must be unique.',
    )

    @api.depends('active')
    def _compute_x_workcenter_status(self):
        for workcenter in self:
            workcenter.x_workcenter_status = 'active' if workcenter.active else 'inactive'

    def _inverse_x_workcenter_status(self):
        for workcenter in self:
            target_active = workcenter.x_workcenter_status == 'active'
            if workcenter.active != target_active:
                workcenter.active = target_active

    def _search_x_workcenter_status(self, operator, value):
        if operator not in ('=', '!=') or value not in ('active', 'inactive'):
            raise ValidationError(_('Unsupported work center status search.'))
        active_value = value == 'active'
        if operator == '!=':
            active_value = not active_value
        return [('active', '=', active_value)]

    @api.depends('x_production_line_id', 'x_workshop_id')
    def _compute_x_workcenter_type(self):
        for workcenter in self:
            if workcenter.x_production_line_id:
                workcenter.x_workcenter_type = 'line'
            elif workcenter.x_workshop_id:
                workcenter.x_workcenter_type = 'workshop'
            else:
                workcenter.x_workcenter_type = False

    @api.constrains('x_workshop_id', 'x_production_line_id')
    def _check_ownership_scope(self):
        for workcenter in self:
            if not workcenter.x_workshop_id:
                raise ValidationError(_('The workshop is required.'))
            if workcenter.x_production_line_id and workcenter.x_production_line_id.workshop_id != workcenter.x_workshop_id:
                raise ValidationError(_('The production line must belong to the selected workshop.'))

    @api.constrains('x_operation_id')
    def _check_operation_required(self):
        for workcenter in self:
            if not workcenter.x_operation_id:
                raise ValidationError(_('A work center must be linked to an operation.'))

    @api.onchange('x_workshop_id')
    def _onchange_x_workshop_id(self):
        for workcenter in self:
            if workcenter.x_workshop_id and workcenter.company_id != workcenter.x_workshop_id.company_id:
                workcenter.company_id = workcenter.x_workshop_id.company_id
            if workcenter.x_production_line_id and workcenter.x_production_line_id.workshop_id != workcenter.x_workshop_id:
                workcenter.x_production_line_id = False

    @api.onchange('x_production_line_id')
    def _onchange_x_production_line_id(self):
        for workcenter in self:
            if workcenter.x_production_line_id:
                workcenter.x_workshop_id = workcenter.x_production_line_id.workshop_id
                workcenter.company_id = workcenter.x_production_line_id.company_id

    def _check_can_deactivate(self):
        active_workorders = self.env['mrp.workorder'].search_count([
            ('workcenter_id', 'in', self.ids),
            ('state', '=', 'progress'),
        ], limit=1)
        if active_workorders:
            raise ValidationError(_('You cannot deactivate a work center with work orders in progress.'))

    def write(self, vals):
        if vals.get('x_workcenter_status') == 'inactive' or vals.get('active') is False:
            self._check_can_deactivate()
        return super().write(vals)

    def action_archive(self):
        self._check_can_deactivate()
        return super().action_archive()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                code = self.env['ir.sequence'].next_by_code('mrp.workcenter')
                if not code:
                    raise UserError(_(
                        'The coding rule is not configured. Please create an ir.sequence '
                        'with code %s in Settings > Technical > Sequences.'
                    ) % 'mrp.workcenter')
                vals['code'] = code
        return super().create(vals_list)


class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

    x_station_type = fields.Selection(
        related='x_route_operation_id.x_station_type',
        string='Station Type',
        store=True,
        readonly=True,
        index=True,
    )

    @api.constrains('workcenter_id')
    def _check_workcenter_enabled(self):
        for operation in self:
            if operation.workcenter_id and not operation.workcenter_id.active:
                raise ValidationError(_('Inactive work centers cannot be used in process routes.'))


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    x_workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        compute='_compute_x_process_scope',
        store=True,
        check_company=True,
        index=True,
    )

    @api.depends(
        'x_process_route_id.x_workshop_id',
    )
    def _compute_x_process_scope(self):
        for bom in self:
            route = bom.x_process_route_id
            bom.x_workshop_id = route.x_workshop_id
