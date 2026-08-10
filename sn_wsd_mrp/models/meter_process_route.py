from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .constants import STATION_TYPE_SELECTION


class SnWsdOperation(models.Model):
    _name = 'sn.wsd.operation'
    _description = 'Standard Operation'
    _order = 'code, id'
    _check_company_auto = True

    code = fields.Char(string='Operation Code', required=True, index=True)
    name = fields.Char(string='Operation', required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    x_workcenter_ids = fields.Many2many(
        'mrp.workcenter',
        'sn_wsd_operation_workcenter_rel',
        'operation_id',
        'workcenter_id',
        string='Work Centers',
        check_company=True,
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        help='Work centers that can execute this operation.',
    )
    x_station_type = fields.Selection(
        STATION_TYPE_SELECTION,
        string='Station Type',
        default='assembly',
        required=True,
    )
    time_mode = fields.Selection(
        [('manual', 'Fixed'), ('auto', 'Computed')],
        string='Duration Computation',
        default='manual',
        required=True,
    )
    time_mode_batch = fields.Integer(string='Computed On Last', default=10)
    time_cycle_manual = fields.Float(string='Manual Duration', default=60)
    cost_mode = fields.Selection(
        [('actual', 'Actual time'), ('estimated', 'Theorical time')],
        string='Cost Based On',
        default='actual',
        required=True,
    )
    note = fields.Text(string='Notes')

    _operation_code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The operation code must be unique per company.',
    )

class MeterProcessRoute(models.Model):
    _name = 'sn.wsd.process.route'
    _description = 'Meter Process Route'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name, version, id'
    _check_company_auto = True

    name = fields.Char(string='Route Name', required=True)
    code = fields.Char(string='Route Code', required=True, index=True)
    version = fields.Char(string='Version', required=True, default='1.0')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    # PLM fields
    x_plm_state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('review', 'In Review'),
            ('released', 'Released'),
            ('obsolete', 'Obsolete'),
            ('cancelled', 'Cancelled'),
        ],
        string='PLM Status',
        default='draft',
        required=True,
        index=True,
        tracking=True,
    )
    x_revision = fields.Char(
        string='Revision',
        default='A.0',
        required=True,
        tracking=True,
    )
    x_previous_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Previous Revision',
        check_company=True,
        copy=False,
    )
    x_source_engineering_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Source Engineering Route',
        check_company=True,
        copy=False,
    )
    x_production_route_ids = fields.One2many(
        'sn.wsd.process.route',
        'x_source_engineering_route_id',
        string='Production Routes',
    )
    x_production_route_count = fields.Integer(
        string='Production Route Count',
        compute='_compute_x_production_route_count',
    )
    x_effective_date = fields.Datetime(
        string='Effective Date',
        copy=False,
        tracking=True,
    )
    x_expire_date = fields.Datetime(
        string='Expiration Date',
        copy=False,
        tracking=True,
    )
    x_released_by = fields.Many2one(
        'res.users',
        string='Released By',
        copy=False,
        readonly=True,
    )
    x_released_date = fields.Datetime(
        string='Released On',
        copy=False,
        readonly=True,
    )
    x_is_current_revision = fields.Boolean(
        string='Current Revision',
        compute='_compute_x_is_current_revision',
        search='_search_x_is_current_revision',
    )
    x_workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        required=True,
        check_company=True,
        index=True,
    )
    meter_product_type = fields.Selection(
        [
            ('single_phase', 'Single Phase'),
            ('three_phase', 'Three Phase'),
            ('collector', 'Collector'),
            ('terminal', 'Terminal'),
            ('other', 'Other'),
        ],
        string='Meter Product Type',
    )
    bom_ids = fields.One2many(
        'mrp.bom',
        'x_process_route_id',
        string='Linked Bills of Material',
    )
    bom_count = fields.Integer(
        string='Linked BoM Count',
        compute='_compute_route_counts',
    )
    route_operation_ids = fields.One2many(
        'sn.wsd.process.route.operation',
        'route_id',
        string='Route Operations',
        copy=True,
    )
    operation_count = fields.Integer(
        string='Route Operation Count',
        compute='_compute_route_counts',
    )
    note = fields.Text(string='Notes')

    _route_code_version_company_uniq = models.Constraint(
        'unique(company_id, code, version)',
        'The process route code and version must be unique per company.',
    )

    @api.depends('bom_ids', 'route_operation_ids')
    def _compute_route_counts(self):
        for route in self:
            route.bom_count = len(route.bom_ids)
            route.operation_count = len(route.route_operation_ids)

    @api.depends('x_production_route_ids')
    def _compute_x_production_route_count(self):
        for route in self:
            route.x_production_route_count = len(route.x_production_route_ids)

    def _compute_x_is_current_revision(self):
        for route in self:
            if route.x_plm_state != 'released':
                route.x_is_current_revision = False
                continue
            domain = route._get_revision_family_domain()
            domain += [('id', '!=', route.id)]
            domain += [('x_plm_state', '=', 'released')]
            domain += [('active', '=', True)]
            route.x_is_current_revision = not bool(self.search_count(domain, limit=1))

    def _search_x_is_current_revision(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        released_routes = self.search([('x_plm_state', '=', 'released'), ('active', '=', True)])
        current_routes = released_routes.filtered('x_is_current_revision')
        domain = [('id', 'in', current_routes.ids)]
        if (operator == '=' and not value) or (operator == '!=' and value):
            domain = [('id', 'not in', current_routes.ids)]
        return domain

    def _get_revision_family_domain(self):
        self.ensure_one()
        domain = [('company_id', 'in', [False, self.company_id.id])]
        domain += [('code', '=', self.code)]
        if self.x_source_engineering_route_id:
            domain += [('x_source_engineering_route_id', '=', self.x_source_engineering_route_id.id)]
        else:
            domain += [('x_source_engineering_route_id', '=', False)]
        return domain

    @api.constrains('x_effective_date', 'x_expire_date')
    def _check_x_effective_dates(self):
        for route in self:
            if route.x_effective_date and route.x_expire_date and route.x_effective_date >= route.x_expire_date:
                raise ValidationError(_('The effective date must be earlier than the expiration date.'))

    @api.onchange('x_workshop_id')
    def _onchange_x_workshop_id(self):
        for route in self:
            if route.x_workshop_id:
                route.company_id = route.x_workshop_id.company_id

    @api.constrains('company_id', 'x_workshop_id')
    def _check_scope(self):
        for route in self:
            if route.x_workshop_id.company_id != route.company_id:
                raise ValidationError(_('The workshop must belong to the same company as the process route.'))

    def name_get(self):
        result = []
        for route in self:
            label = ' / '.join(filter(None, [route.code, route.version, route.name]))
            result.append((route.id, label))
        return result

    def _sync_linked_bom_operations(self):
        for route in self:
            route.bom_ids._sync_process_route_operations()

    def action_open_linked_bom(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Linked Bill of Material',
            'res_model': 'mrp.bom',
        }
        if len(self.bom_ids) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.bom_ids.id,
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'domain': [('id', 'in', self.bom_ids.ids)],
            })
        return action

    def _get_next_revision(self):
        self.ensure_one()
        revision = self.x_revision or 'A.0'
        if '.' in revision:
            prefix, suffix = revision.rsplit('.', 1)
            if suffix.isdigit():
                return f'{prefix}.{int(suffix) + 1}'
        return f'{revision}.1'

    def _get_next_version(self):
        self.ensure_one()
        version = self.version or '1.0'
        if '.' in version:
            prefix, suffix = version.rsplit('.', 1)
            if suffix.isdigit():
                next_number = int(suffix) + 1
                next_version = f'{prefix}.{next_number}'
                while self.search_count([
                    ('company_id', '=', self.company_id.id),
                    ('code', '=', self.code),
                    ('version', '=', next_version),
                ], limit=1):
                    next_number += 1
                    next_version = f'{prefix}.{next_number}'
                return next_version
        next_version = f'{version}.1'
        while self.search_count([
            ('company_id', '=', self.company_id.id),
            ('code', '=', self.code),
            ('version', '=', next_version),
        ], limit=1):
            next_version = f'{next_version}.1'
        return next_version

    def action_submit_review(self):
        self.filtered(lambda route: route.x_plm_state == 'draft').write({'x_plm_state': 'review'})
        return True

    def action_reset_draft(self):
        self.filtered(lambda route: route.x_plm_state in ('review', 'cancelled')).write({'x_plm_state': 'draft'})
        return True

    def action_cancel_plm(self):
        self.filtered(lambda route: route.x_plm_state in ('draft', 'review')).write({'x_plm_state': 'cancelled'})
        return True

    def action_release_plm(self):
        for route in self:
            previous_revisions = self.search(
                route._get_revision_family_domain() + [('id', '!=', route.id), ('x_plm_state', '=', 'released')]
            )
            previous_revisions.with_context(allow_plm_locked_write=True).write({
                'x_plm_state': 'obsolete',
                'active': False,
                'x_expire_date': fields.Datetime.now(),
            })
            route.with_context(allow_plm_locked_write=True).write({
                'x_plm_state': 'released',
                'active': True,
                'x_released_by': self.env.user.id,
                'x_released_date': fields.Datetime.now(),
            })
        return True

    def action_create_new_revision(self):
        self.ensure_one()
        if self.x_plm_state == 'cancelled':
            raise UserError(_('Cancelled process routes cannot be copied into a new revision.'))
        new_route = self.copy(default={
            'version': self._get_next_version(),
            'x_plm_state': 'draft',
            'x_revision': self._get_next_revision(),
            'x_previous_route_id': self.id,
            'x_released_by': False,
            'x_released_date': False,
            'x_effective_date': False,
            'x_expire_date': False,
            'active': True,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Route Revision'),
            'res_model': 'sn.wsd.process.route',
            'res_id': new_route.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_create_production_route(self):
        self.ensure_one()
        if self.x_plm_state not in ('review', 'released'):
            raise UserError(_('Submit or release the engineering process route before generating a production route.'))
        new_route = self.copy(default={
            'x_plm_state': 'draft',
            'x_source_engineering_route_id': self.id,
            'x_previous_route_id': False,
            'x_released_by': False,
            'x_released_date': False,
            'x_effective_date': False,
            'x_expire_date': False,
            'active': True,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Production Route'),
            'res_model': 'sn.wsd.process.route',
            'res_id': new_route.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_open_production_routes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Production Routes'),
            'res_model': 'sn.wsd.process.route',
            'view_mode': 'list,form',
            'domain': [('x_source_engineering_route_id', '=', self.id)],
        }


class MeterProcessRouteOperation(models.Model):
    _name = 'sn.wsd.process.route.operation'
    _description = 'Meter Process Route Operation'
    _order = 'route_id, sequence, id'
    _check_company_auto = True

    route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='route_id.company_id',
        store=True,
        readonly=True,
    )
    route_workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Route Workshop',
        related='route_id.x_workshop_id',
        store=True,
        readonly=True,
    )
    available_operation_ids = fields.Many2many(
        'sn.wsd.operation',
        compute='_compute_available_ids',
    )
    available_workcenter_ids = fields.Many2many(
        'mrp.workcenter',
        compute='_compute_available_ids',
    )
    operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='Operation',
        required=True,
        check_company=True,
        index=True,
        domain="[('id', 'in', available_operation_ids)]",
    )
    name = fields.Char(
        string='Operation Name',
        related='operation_id.name',
        store=True,
        readonly=True,
    )
    sequence = fields.Integer(string='Sequence', default=100)
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        required=True,
        check_company=True,
        index=True,
        domain="[('id', 'in', available_workcenter_ids)]",
    )
    x_step_code = fields.Char(
        string='Route Operation Code',
        related='operation_id.code',
        store=True,
        readonly=True,
        index=True,
    )
    x_station_type = fields.Selection(
        related='operation_id.x_station_type',
        string='Station Type',
        store=True,
        readonly=True,
        index=True,
    )
    time_mode = fields.Selection(
        [('manual', 'Fixed'), ('auto', 'Computed')],
        string='Duration Computation',
        default='manual',
    )
    time_mode_batch = fields.Integer(string='Computed On Last', default=10)
    time_cycle_manual = fields.Float(string='Manual Duration', default=60)
    cost_mode = fields.Selection(
        [('actual', 'Actual time'), ('estimated', 'Theorical time')],
        string='Cost Based On',
        default='actual',
    )
    blocked_by_route_operation_ids = fields.Many2many(
        'sn.wsd.process.route.operation',
        relation='sn_wsd_process_route_operation_rel',
        column1='operation_id',
        column2='blocked_by_id',
        string='Blocked By',
        domain="[('route_id', '=', route_id), ('id', '!=', id)]",
        copy=False,
    )
    x_allow_entry = fields.Boolean(
        string='Allow Entry',
        help='Allow serials without a previous route event to enter this operation.',
    )
    x_allow_serial_creation = fields.Boolean(
        string='Allow Serial Creation',
        help='Allow the API to create a production-stage serial at this entry operation.',
    )
    x_allow_reentry = fields.Boolean(
        string='Allow Reentry',
        help='Allow a serial to be processed again on the same operation.',
    )
    x_allow_repair_return = fields.Boolean(
        string='Allow Repair Return',
        help='Allow serials returning from a repair station to enter this operation.',
    )
    x_allow_skip_with_override = fields.Boolean(
        string='Allow Skip With Override',
        help='Allow this operation to be reached with an explicit route override.',
    )
    x_ng_retry_limit = fields.Integer(
        string='NG Retry Limit',
        default=0,
        help='Maximum NG scan-pass attempts allowed before the serial must enter repair. Set 0 for no automatic repair threshold.',
    )
    needed_by_route_operation_ids = fields.Many2many(
        'sn.wsd.process.route.operation',
        relation='sn_wsd_process_route_operation_rel',
        column1='blocked_by_id',
        column2='operation_id',
        string='Blocks',
        domain="[('route_id', '=', route_id), ('id', '!=', id)]",
        copy=False,
    )
    bom_operation_ids = fields.One2many(
        'mrp.routing.workcenter',
        'x_route_operation_id',
        string='Projected BoM Operations',
        readonly=True,
    )
    bom_operation_count = fields.Integer(
        string='Projected BoM Operation Count',
        compute='_compute_bom_operation_count',
    )

    _route_operation_code_uniq = models.Constraint(
        'unique(route_id, operation_id)',
        'The operation must be unique within one process route.',
    )

    @api.depends('bom_operation_ids')
    def _compute_bom_operation_count(self):
        for operation in self:
            operation.bom_operation_count = len(operation.bom_operation_ids)

    @api.depends(
        'route_id.x_workshop_id',
        'company_id',
        'operation_id',
        'operation_id.x_workcenter_ids',
    )
    def _compute_available_ids(self):
        operation_model = self.env['sn.wsd.operation']
        workcenter_model = self.env['mrp.workcenter']
        for route_operation in self:
            operation_domain = [('company_id', '=', route_operation.company_id.id)]
            workcenter_domain = [('company_id', '=', route_operation.company_id.id), ('active', '=', True)]
            if route_operation.route_workshop_id:
                workcenter_domain.append(('x_workshop_id', '=', route_operation.route_workshop_id.id))
            route_operation.available_operation_ids = operation_model.search(operation_domain)
            if route_operation.operation_id:
                workcenter_domain.append(('id', 'in', route_operation.operation_id.x_workcenter_ids.ids))
            route_operation.available_workcenter_ids = workcenter_model.search(workcenter_domain)

    def _prepare_bom_operation_values(self, bom):
        self.ensure_one()
        return {
            'name': self.name,
            'bom_id': bom.id,
            'workcenter_id': self.workcenter_id.id,
            'sequence': self.sequence,
            'time_mode': self.time_mode,
            'time_mode_batch': self.time_mode_batch,
            'time_cycle_manual': self.time_cycle_manual,
            'cost_mode': self.cost_mode,
            'x_route_operation_id': self.id,
            'x_step_code': self.x_step_code,
            'x_station_type': self.x_station_type,
            'x_allow_entry': self.x_allow_entry,
            'x_allow_serial_creation': self.x_allow_serial_creation,
            'x_allow_reentry': self.x_allow_reentry,
            'x_allow_repair_return': self.x_allow_repair_return,
            'x_allow_skip_with_override': self.x_allow_skip_with_override,
            'x_ng_retry_limit': self.x_ng_retry_limit,
        }

    @api.onchange('operation_id')
    def _onchange_operation_id_apply_defaults(self):
        for operation in self:
            template = operation.operation_id
            if not template:
                continue
            if template.x_workcenter_ids:
                operation.workcenter_id = template.x_workcenter_ids[:1]
            else:
                operation.workcenter_id = False
            operation.time_mode = template.time_mode
            operation.time_mode_batch = template.time_mode_batch
            operation.time_cycle_manual = template.time_cycle_manual
            operation.cost_mode = template.cost_mode

    @api.constrains('route_id', 'company_id', 'operation_id', 'workcenter_id')
    def _check_company_scope(self):
        for operation in self:
            if operation.operation_id.company_id != operation.company_id:
                raise ValidationError(_('The operation must belong to the same company as the process route.'))
            if operation.workcenter_id.company_id != operation.company_id:
                raise ValidationError(_('The work center must belong to the same company as the process route.'))
            if operation.workcenter_id not in operation.operation_id.x_workcenter_ids:
                raise ValidationError(_('The work center must be linked to the selected operation.'))
            if operation.route_workshop_id:
                if operation.workcenter_id.x_workshop_id != operation.route_workshop_id:
                    raise ValidationError(_('The selected work center must belong to the current workshop.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped('route_id')._sync_linked_bom_operations()
        return records

    def write(self, vals):
        result = super().write(vals)
        self.mapped('route_id')._sync_linked_bom_operations()
        return result

    def unlink(self):
        routes = self.mapped('route_id')
        result = super().unlink()
        routes._sync_linked_bom_operations()
        return result


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    x_process_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        required=True,
        check_company=True,
        index=True,
    )

    @api.constrains('x_process_route_id', 'company_id')
    def _check_process_route_scope(self):
        for bom in self:
            if not bom.x_process_route_id:
                raise ValidationError(_('The process route is required on the bill of material.'))
            route = bom.x_process_route_id
            if route.company_id != bom.company_id:
                raise ValidationError(_('The process route must belong to the same company as the bill of material.'))

    @api.model_create_multi
    def create(self, vals_list):
        boms = super().create(vals_list)
        boms.filtered('x_process_route_id')._sync_process_route_operations()
        return boms

    def write(self, vals):
        result = super().write(vals)
        if {'x_process_route_id', 'company_id'}.intersection(vals):
            self._sync_process_route_operations()
        return result

    def _sync_process_route_operations(self):
        for bom in self:
            route = bom.x_process_route_id
            route_operations = route.route_operation_ids.sorted(lambda operation: (operation.sequence, operation.id)) \
                if route else self.env['sn.wsd.process.route.operation']

            # The process route is the single source of truth for BoM operations.
            # Rebuild the BoM operations from scratch so deleted or detached route
            # operations cannot remain as stale rows on the BoM or MO.
            if bom.operation_ids:
                bom.operation_ids.unlink()

            workorder_map = {}
            for route_operation in route_operations:
                bom_operation = self.env['mrp.routing.workcenter'].create(
                    route_operation._prepare_bom_operation_values(bom)
                )
                workorder_map[route_operation.id] = bom_operation

            for route_operation in route_operations:
                bom_operation = workorder_map.get(route_operation.id)
                if not bom_operation:
                    continue
                bom_operation.blocked_by_operation_ids = [
                    fields.Command.set([
                        workorder_map[dependency.id].id
                        for dependency in route_operation.blocked_by_route_operation_ids
                        if dependency.id in workorder_map
                    ])
                ]

            draft_productions = self.env['mrp.production'].search([
                ('bom_id', '=', bom.id),
                ('state', '=', 'draft'),
            ])
            for production in draft_productions:
                production._link_bom(bom)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_process_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        related='bom_id.x_process_route_id',
        store=True,
        readonly=True,
    )


class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

    x_process_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        related='bom_id.x_process_route_id',
        store=True,
        readonly=True,
        index=True,
    )
    x_route_operation_id = fields.Many2one(
        'sn.wsd.process.route.operation',
        string='Route Operation Template',
        ondelete='set null',
        index=True,
        check_company=True,
        copy=False,
    )
    x_step_code = fields.Char(string='Route Operation Code', index=True)
    x_allow_entry = fields.Boolean(
        string='Allow Entry',
        help='Allow serials without a previous route event to enter this BoM operation.',
    )
    x_allow_serial_creation = fields.Boolean(
        string='Allow Serial Creation',
        help='Allow the API to create a production-stage serial at this BoM operation.',
    )
    x_allow_reentry = fields.Boolean(
        string='Allow Reentry',
        help='Allow a serial to be processed again on the same BoM operation.',
    )
    x_allow_repair_return = fields.Boolean(
        string='Allow Repair Return',
        help='Allow serials returning from a repair station to enter this BoM operation.',
    )
    x_allow_skip_with_override = fields.Boolean(
        string='Allow Skip With Override',
        help='Allow this BoM operation to be reached with an explicit route override.',
    )
    x_ng_retry_limit = fields.Integer(
        string='NG Retry Limit',
        default=0,
        help='Maximum NG scan-pass attempts allowed before the serial must enter repair. Set 0 for no automatic repair threshold.',
    )

    @api.constrains('x_route_operation_id', 'bom_id')
    def _check_route_projection(self):
        for operation in self.filtered('x_route_operation_id'):
            if operation.x_route_operation_id.route_id != operation.bom_id.x_process_route_id:
                raise ValidationError(_('The projected operation must belong to the process route selected on the bill of material.'))
