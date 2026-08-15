from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare

from .constants import STATION_TYPE_SELECTION


class SnManufacturingBatch(models.Model):
    _name = 'sn.wsd.manufacturing.batch'
    _description = 'Manufacturing Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Batch Reference',
        required=True,
        copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('sn.wsd.manufacturing.batch') or _('New'),
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True,
    )
    product_id = fields.Many2one('product.product', string='Product', required=True, check_company=True, index=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True)
    bom_id = fields.Many2one('mrp.bom', string='Bill of Material', check_company=True, index=True)
    route_id = fields.Many2one('sn.wsd.process.route', string='Process Route', check_company=True, index=True)
    route_revision = fields.Char(string='Route Revision', copy=False)
    origin_production_id = fields.Many2one('mrp.production', string='Origin Manufacturing Order', check_company=True, index=True)
    production_group_id = fields.Many2one('mrp.production.group', string='Manufacturing Order Group', index=True)
    production_ids = fields.One2many('mrp.production', 'x_manufacturing_batch_id', string='Manufacturing Orders')
    internal_serial_ids = fields.One2many('sn.wsd.internal.serial', 'manufacturing_batch_id', string='Internal Serials')
    operation_snapshot_ids = fields.One2many(
        'sn.wsd.manufacturing.batch.operation',
        'batch_id',
        string='Route Operation Snapshots',
        copy=False,
    )
    production_count = fields.Integer(string='Manufacturing Order Count', compute='_compute_counts')
    internal_serial_count = fields.Integer(string='Internal Serial Count', compute='_compute_counts')
    active_internal_serial_count = fields.Integer(
        string='Active Internal Serial Count',
        compute='_compute_internal_serial_capacity',
    )
    missing_internal_serial_count = fields.Integer(
        string='Missing Internal Serial Count',
        compute='_compute_internal_serial_capacity',
    )
    can_generate_internal_serials = fields.Boolean(compute='_compute_internal_serial_capacity')
    operation_snapshot_count = fields.Integer(string='Route Operation Count', compute='_compute_counts')
    planned_qty = fields.Float(
        string='Planned Quantity',
        compute='_compute_planned_qty',
        store=True,
        tracking=True,
    )
    completed_qty = fields.Float(string='Completed Quantity', compute='_compute_quantities', store=True)
    produced_qty = fields.Float(string='Produced Quantity', compute='_compute_quantities', store=True)
    remaining_qty = fields.Float(string='Remaining Quantity', compute='_compute_quantities', store=True)
    wip_qty = fields.Float(string='WIP Quantity', compute='_compute_quantities', store=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('in_progress', 'In Progress'),
            ('partial_done', 'Partially Done'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ], string='Status', compute='_compute_state', store=True, default='draft', required=True, tracking=True, index=True,
    )
    date_start = fields.Datetime(string='Start Date', compute='_compute_dates', store=True)
    date_finished = fields.Datetime(string='Finished Date', compute='_compute_dates', store=True)
    note = fields.Text(string='Notes')

    _batch_name_company_uniq = models.Constraint(
        'unique(company_id, name)',
        'The manufacturing batch reference must be unique per company.',
    )

    @api.depends('production_ids', 'internal_serial_ids', 'operation_snapshot_ids')
    def _compute_counts(self):
        for batch in self:
            batch.production_count = len(batch.production_ids)
            batch.internal_serial_count = len(batch.internal_serial_ids)
            batch.operation_snapshot_count = len(batch.operation_snapshot_ids)

    @api.depends(
        'production_ids.product_qty',
        'production_ids.product_uom_id',
        'production_ids.state',
    )
    def _compute_planned_qty(self):
        for batch in self:
            productions = batch.production_ids.filtered(lambda production: production.state != 'cancel')
            batch.planned_qty = sum(
                production.product_uom_id._compute_quantity(
                    production.product_qty,
                    batch.product_uom_id,
                )
                for production in productions
            ) if batch.product_uom_id else 0.0

    @api.depends(
        'planned_qty',
        'state',
        'production_ids.x_has_meter_operations',
        'production_ids.workorder_ids.sequence',
        'production_ids.workorder_ids.state',
        'production_ids.workorder_ids.operation_id.x_allow_serial_creation',
        'internal_serial_ids.active',
        'internal_serial_ids.final_result',
    )
    def _compute_internal_serial_capacity(self):
        for batch in self:
            productions = batch.production_ids.filtered(lambda production: production.state != 'cancel')
            first_operations_allow_serial_creation = bool(productions) and all(
                batch._get_first_workorder(production).operation_id.x_allow_serial_creation
                for production in productions
            )
            active_serials = batch.internal_serial_ids.filtered(
                lambda serial: serial.active and not serial.is_confirmed_scrapped()
            )
            target_count = batch._get_internal_serial_target_count(raise_if_invalid=False)
            batch.active_internal_serial_count = len(active_serials)
            batch.missing_internal_serial_count = max(target_count - len(active_serials), 0)
            batch.can_generate_internal_serials = bool(
                batch.missing_internal_serial_count
                and batch.state not in ('done', 'cancelled')
                and first_operations_allow_serial_creation
            )

    def _get_first_workorder(self, production):
        self.ensure_one()
        return production.workorder_ids.filtered(
            lambda workorder: workorder.state != 'cancel'
        ).sorted(lambda workorder: (workorder.sequence, workorder.id))[:1]

    def _get_internal_serial_target_count(self, raise_if_invalid=True):
        self.ensure_one()
        target_count = int(round(self.planned_qty))
        if self.product_uom_id and float_compare(
            self.planned_qty,
            target_count,
            precision_digits=6,
        ) != 0:
            if raise_if_invalid:
                raise ValidationError(_(
                    'The manufacturing batch planned quantity must be a whole number before internal serials can be generated.'
                ))
            return 0
        return max(target_count, 0)

    def _lock_internal_serial_capacity(self):
        self.ensure_one()
        self.env.cr.execute(
            'SELECT id FROM sn_wsd_manufacturing_batch WHERE id = %s FOR UPDATE',
            [self.id],
        )

    def _get_active_internal_serials(self):
        self.ensure_one()
        serials = self.env['sn.wsd.internal.serial'].with_context(active_test=False).search([
            ('manufacturing_batch_id', '=', self.id),
            ('active', '=', True),
        ])
        return serials.filtered(lambda serial: not serial.is_confirmed_scrapped())

    def _get_internal_serial_production_slots(self, productions, active_serials, missing_count):
        self.ensure_one()
        slots = []
        for production in productions.sorted(lambda record: (record.backorder_sequence, record.id)):
            production_qty = production.product_uom_id._compute_quantity(
                production.product_qty,
                self.product_uom_id,
            )
            target_count = int(round(production_qty))
            if float_compare(
                production_qty,
                target_count,
                precision_digits=6,
            ) != 0:
                raise ValidationError(_(
                    'Manufacturing order %(production)s must have a whole-number quantity before internal serials can be generated.'
                ) % {'production': production.display_name})
            assigned_count = len(active_serials.filtered(
                lambda serial: serial.current_production_id == production
            ))
            slots.extend([production] * max(target_count - assigned_count, 0))
        if len(slots) < missing_count:
            fallback = (
                self.origin_production_id.filtered(lambda production: production.state != 'cancel')
                or productions.sorted(lambda production: production.id)[:1]
            )
            slots.extend([fallback] * (missing_count - len(slots)))
        return slots[:missing_count]

    def _prepare_internal_serial_values_list(self, production_slots, scrapped_serials=False, identity_origin_type=False):
        self.ensure_one()
        scrapped_serials = scrapped_serials or self.env['sn.wsd.internal.serial']
        values_list = []
        for index, slot_production in enumerate(production_slots):
            replaced_serial = scrapped_serials[index:index + 1]
            production = (
                replaced_serial.current_production_id.filtered(lambda record: record.state != 'cancel')
                or replaced_serial.production_id.filtered(lambda record: record.state != 'cancel')
                or slot_production
            )
            serial_no = (
                self.env['ir.sequence'].next_by_code('sn.wsd.internal.serial.no')
                or self.env['ir.sequence'].next_by_code('sn.wsd.internal.serial')
            )
            if not serial_no:
                raise UserError(_('No internal serial number sequence is configured.'))
            values = {
                'serial_no': serial_no,
                'barcode': serial_no,
                'product_id': self.product_id.id,
                'production_id': production.id,
                'current_production_id': production.id,
                'manufacturing_batch_id': self.id,
                'company_id': self.company_id.id,
                'serial_type': 'finished' if production.x_has_meter_operations else 'semifinished',
                'firmware_version': production.x_firmware_version,
                'customer_batch_no': production.x_delivery_batch_no,
                'replaces_serial_id': replaced_serial.id,
            }
            if identity_origin_type:
                values['identity_origin_type'] = identity_origin_type
            values_list.append(values)
        return values_list

    def _generate_internal_serials(self, quantity=None):
        self.ensure_one()
        self._lock_internal_serial_capacity()
        if self.state in ('done', 'cancelled'):
            raise UserError(_('Internal serials cannot be generated for a closed manufacturing batch.'))
        productions = self.production_ids.filtered(lambda production: production.state != 'cancel')
        if not productions:
            raise UserError(_('The manufacturing batch has no active manufacturing orders.'))
        productions_without_serial_creation = productions.filtered(
            lambda production: not self._get_first_workorder(production).operation_id.x_allow_serial_creation
        )
        if productions_without_serial_creation:
            raise UserError(_(
                'The first operation of every manufacturing order must allow serial creation. '
                'Check the following manufacturing orders: %(productions)s.'
            ) % {
                'productions': ', '.join(productions_without_serial_creation.mapped('display_name')),
            })
        target_count = self._get_internal_serial_target_count()
        active_serials = self._get_active_internal_serials()
        missing_count = max(target_count - len(active_serials), 0)
        if not missing_count:
            raise UserError(_('The manufacturing batch already has all required active internal serials.'))
        generate_count = missing_count
        if quantity is not None:
            generate_count = int(quantity)
            if generate_count <= 0:
                raise UserError(_('The internal serial generation quantity must be positive.'))
            if generate_count > missing_count:
                raise UserError(_(
                    'The internal serial generation quantity cannot exceed the remaining quantity %(remaining)s.'
                ) % {'remaining': missing_count})

        production_slots = self._get_internal_serial_production_slots(
            productions,
            active_serials,
            generate_count,
        )
        scrapped_serials = self.internal_serial_ids.filtered(
            lambda serial: serial.is_confirmed_scrapped() and not serial.replacement_serial_ids
        ).sorted(lambda serial: (serial.production_date, serial.id))
        values_list = self._prepare_internal_serial_values_list(production_slots, scrapped_serials=scrapped_serials)
        return self.env['sn.wsd.internal.serial'].create(values_list)

    def _generate_laser_internal_serials(self, production, quantity):
        self.ensure_one()
        self._lock_internal_serial_capacity()
        if self.state in ('done', 'cancelled'):
            raise UserError(_('Internal serials cannot be generated for a closed manufacturing batch.'))
        if not production or production.state == 'cancel' or production.x_manufacturing_batch_id != self:
            raise UserError(_('The manufacturing order must belong to the manufacturing batch.'))
        generate_count = int(quantity or 0)
        if generate_count <= 0:
            raise UserError(_('The internal serial generation quantity must be positive.'))
        active_serials = self._get_active_internal_serials()
        target_count = self._get_internal_serial_target_count()
        missing_count = max(target_count - len(active_serials), 0)
        if generate_count > missing_count:
            raise UserError(_(
                'The internal serial generation quantity cannot exceed the remaining quantity %(remaining)s.'
            ) % {'remaining': missing_count})
        production_slots = [production] * generate_count
        values_list = self._prepare_internal_serial_values_list(
            production_slots,
            identity_origin_type='laser',
        )
        return self.env['sn.wsd.internal.serial'].create(values_list)

    def _post_internal_serial_generation_message(self, serials):
        self.ensure_one()
        serial_numbers = serials.mapped('serial_no')
        if not serial_numbers:
            return
        self.message_post(body=_(
            'Generated %(count)s internal serials for the manufacturing batch. '
            'Serial range: %(first)s to %(last)s.'
        ) % {
            'count': len(serials),
            'first': serial_numbers[0],
            'last': serial_numbers[-1],
        })

    def action_generate_missing_internal_serials(self):
        self.ensure_one()
        serials = self._generate_internal_serials()
        self._post_internal_serial_generation_message(serials)
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    @api.model_create_multi
    def create(self, vals_list):
        batches = super().create(vals_list)
        batches._refresh_route_snapshot()
        return batches

    @api.depends(
        'production_ids.qty_produced', 'production_ids.product_qty',
        'production_ids.state', 'production_ids.x_batch_role',
        'production_ids.workorder_ids.qty_produced',
    )
    def _compute_quantities(self):
        for batch in self:
            productions = batch.production_ids.filtered(lambda production: production.state != 'cancel')
            batch.produced_qty = sum(productions.mapped('qty_produced'))
            batch.completed_qty = sum(
                production.qty_produced
                for production in productions
                if production.state == 'done'
            )
            batch.remaining_qty = max(batch.planned_qty - batch.produced_qty, 0.0)
            if batch.internal_serial_ids:
                batch.wip_qty = len(batch.internal_serial_ids)
            else:
                batch.wip_qty = sum(
                    max(max(production.workorder_ids.mapped('qty_produced'), default=0.0) - production.qty_produced, 0.0)
                    for production in productions
                )

    @api.depends('production_ids.date_start', 'production_ids.date_finished')
    def _compute_dates(self):
        for batch in self:
            starts = batch.production_ids.mapped('date_start')
            finishes = batch.production_ids.mapped('date_finished')
            batch.date_start = min(starts) if starts else False
            batch.date_finished = max(finishes) if finishes else False

    @api.depends('production_ids.state', 'planned_qty', 'completed_qty', 'remaining_qty')
    def _compute_state(self):
        for batch in self:
            states = set(batch.production_ids.mapped('state'))
            if not states:
                batch.state = 'draft'
            elif states <= {'cancel'}:
                batch.state = 'cancelled'
            elif batch.remaining_qty <= 0 and states <= {'done', 'cancel'}:
                batch.state = 'done'
            elif batch.completed_qty > 0:
                batch.state = 'partial_done'
            elif states.intersection({'progress', 'to_close', 'confirmed'}):
                batch.state = 'in_progress'
            else:
                batch.state = 'confirmed'

    def _sync_from_production(self, production):
        self.ensure_one()
        values = {
            'company_id': production.company_id.id,
            'product_id': production.product_id.id,
            'product_uom_id': production.product_uom_id.id,
            'bom_id': production.bom_id.id,
            'route_id': production.x_process_route_id.id,
            'route_version': production.x_process_route_id.version if production.x_process_route_id else 0,
            'production_group_id': production.production_group_id.id,
        }
        self.write(values)
        self._refresh_route_snapshot()
        return self

    def _prepare_route_snapshot_values(self, route_operation=False, bom_operation=False):
        self.ensure_one()
        operation = route_operation.operation_id if route_operation else False
        workcenter = route_operation.workcenter_id if route_operation else False
        return {
            'batch_id': self.id,
            'route_id': self.route_id.id,
            'route_revision': self.route_revision,
            'route_operation_id': route_operation.id if route_operation else False,
            'bom_operation_id': bom_operation.id if bom_operation else False,
            'sequence': route_operation.sequence if route_operation else bom_operation.sequence,
            'operation_id': operation.id if operation else False,
            'operation_name': route_operation.name if route_operation else bom_operation.name,
            'workcenter_id': workcenter.id if workcenter else bom_operation.workcenter_id.id,
            'workcenter_code': workcenter.code if workcenter else bom_operation.workcenter_id.code,
            'step_code': route_operation.x_step_code if route_operation else bom_operation.x_step_code,
            'station_type': route_operation.x_station_type if route_operation else bom_operation.x_station_type,
            'time_mode': route_operation.time_mode if route_operation else bom_operation.time_mode,
            'time_mode_batch': route_operation.time_mode_batch if route_operation else bom_operation.time_mode_batch,
            'time_cycle_manual': route_operation.time_cycle_manual if route_operation else bom_operation.time_cycle_manual,
            'cost_mode': route_operation.cost_mode if route_operation else bom_operation.cost_mode,
            'allow_entry': route_operation.x_allow_entry if route_operation else bom_operation.x_allow_entry,
            'allow_reentry': route_operation.x_allow_reentry if route_operation else bom_operation.x_allow_reentry,
            'allow_repair_return': route_operation.x_allow_repair_return if route_operation else bom_operation.x_allow_repair_return,
            'allow_skip_with_override': route_operation.x_allow_skip_with_override if route_operation else bom_operation.x_allow_skip_with_override,
        }

    def _refresh_route_snapshot(self):
        snapshot_model = self.env['sn.wsd.manufacturing.batch.operation']
        for batch in self:
            batch.operation_snapshot_ids.unlink()
            if not batch.route_id:
                continue
            route_operations = batch.route_id.route_operation_ids.sorted(lambda operation: (operation.sequence, operation.id))
            if not route_operations:
                continue
            bom_operations = {
                operation.x_route_operation_id.id: operation
                for operation in batch.bom_id.operation_ids
                if operation.x_route_operation_id
            } if batch.bom_id else {}
            snapshot_by_route_operation = {}
            for route_operation in route_operations:
                snapshot = snapshot_model.create(
                    batch._prepare_route_snapshot_values(
                        route_operation=route_operation,
                        bom_operation=bom_operations.get(route_operation.id),
                    )
                )
                snapshot_by_route_operation[route_operation.id] = snapshot
            for route_operation in route_operations:
                snapshot = snapshot_by_route_operation.get(route_operation.id)
                if not snapshot:
                    continue
                blocked_snapshots = [
                    snapshot_by_route_operation[dependency.id].id
                    for dependency in route_operation.blocked_by_route_operation_ids
                    if dependency.id in snapshot_by_route_operation
                ]
                if blocked_snapshots:
                    snapshot.blocked_by_snapshot_ids = [fields.Command.set(blocked_snapshots)]

    def action_open_productions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Manufacturing Orders'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('x_manufacturing_batch_id', '=', self.id)],
        }

    def action_open_internal_serials(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Internal Serials'),
            'res_model': 'sn.wsd.internal.serial',
            'view_mode': 'list,form',
            'domain': [('manufacturing_batch_id', '=', self.id)],
            'context': {'default_manufacturing_batch_id': self.id, 'default_product_id': self.product_id.id},
        }


class SnManufacturingBatchOperation(models.Model):
    _name = 'sn.wsd.manufacturing.batch.operation'
    _description = 'Manufacturing Batch Route Operation Snapshot'
    _order = 'batch_id, sequence, id'
    _check_company_auto = True

    batch_id = fields.Many2one(
        'sn.wsd.manufacturing.batch',
        string='Manufacturing Batch',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='batch_id.company_id',
        store=True,
        readonly=True,
    )
    route_id = fields.Many2one('sn.wsd.process.route', string='Process Route', check_company=True, index=True)
    route_revision = fields.Char(string='Route Revision', copy=False)
    route_operation_id = fields.Many2one(
        'sn.wsd.process.route.operation',
        string='Source Route Operation',
        check_company=True,
        ondelete='set null',
        index=True,
    )
    bom_operation_id = fields.Many2one(
        'mrp.routing.workcenter',
        string='Projected BoM Operation',
        check_company=True,
        ondelete='set null',
        index=True,
    )
    sequence = fields.Integer(string='Sequence', default=100, index=True)
    operation_id = fields.Many2one('sn.wsd.operation', string='Operation', check_company=True, ondelete='set null', index=True)
    operation_name = fields.Char(string='Operation Name', required=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', check_company=True, ondelete='set null', index=True)
    workcenter_code = fields.Char(string='Work Center Code', index=True)
    step_code = fields.Char(string='Route Operation Code', index=True)
    station_type = fields.Selection(STATION_TYPE_SELECTION, string='Station Type', index=True)
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
    allow_entry = fields.Boolean(string='Allow Entry')
    allow_reentry = fields.Boolean(string='Allow Reentry')
    allow_repair_return = fields.Boolean(string='Allow Repair Return')
    allow_skip_with_override = fields.Boolean(string='Allow Skip With Override')
    blocked_by_snapshot_ids = fields.Many2many(
        'sn.wsd.manufacturing.batch.operation',
        relation='sn_wsd_batch_operation_dependency_rel',
        column1='operation_id',
        column2='blocked_by_id',
        string='Blocked By',
        domain="[('batch_id', '=', batch_id), ('id', '!=', id)]",
        copy=False,
    )
    needed_by_snapshot_ids = fields.Many2many(
        'sn.wsd.manufacturing.batch.operation',
        relation='sn_wsd_batch_operation_dependency_rel',
        column1='blocked_by_id',
        column2='operation_id',
        string='Blocks',
        domain="[('batch_id', '=', batch_id), ('id', '!=', id)]",
        copy=False,
    )


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_manufacturing_batch_id = fields.Many2one(
        'sn.wsd.manufacturing.batch', string='Manufacturing Batch', copy=True,
        check_company=True, index=True, tracking=True,
    )
    x_batch_role = fields.Selection(
        [('origin', 'Origin'), ('backorder', 'Backorder'), ('rework', 'Rework'), ('replacement', 'Replacement')],
        string='Batch Role', default='origin', copy=True, tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        productions = super().create(vals_list)
        batch_model = self.env['sn.wsd.manufacturing.batch']
        for production, vals in zip(productions, vals_list):
            if production.x_manufacturing_batch_id:
                continue
            batch = batch_model.create({
                'company_id': production.company_id.id,
                'product_id': production.product_id.id,
                'product_uom_id': production.product_uom_id.id,
                'bom_id': production.bom_id.id,
                'route_id': production.x_process_route_id.id,
                'route_version': production.x_process_route_id.version if production.x_process_route_id else 0,
                'origin_production_id': production.id,
                'production_group_id': production.production_group_id.id,
            })
            production.write({'x_manufacturing_batch_id': batch.id, 'x_batch_role': 'origin'})
        return productions

    def _get_backorder_mo_vals(self):
        values = super()._get_backorder_mo_vals()
        values.update({'x_batch_role': 'backorder'})
        return values

    def _split_productions(self, amounts=False, cancel_remaining_qty=False, set_consumed_qty=False):
        source_productions = self
        productions = super()._split_productions(
            amounts=amounts,
            cancel_remaining_qty=cancel_remaining_qty,
            set_consumed_qty=set_consumed_qty,
        )
        for source in source_productions:
            backorders = productions.filtered(
                lambda production: production != source
                and production.production_group_id == source.production_group_id
                and production.x_manufacturing_batch_id == source.x_manufacturing_batch_id
                and production.state != 'cancel'
            )
            if len(backorders) != 1:
                continue
            serials = self.env['sn.wsd.internal.serial'].search([
                ('manufacturing_batch_id', '=', source.x_manufacturing_batch_id.id),
                ('current_production_id', '=', source.id),
            ])
            serials.write({'current_production_id': backorders.id})
        return productions

    def action_confirm(self):
        result = super().action_confirm()
        for production in self.filtered(lambda record: record.x_manufacturing_batch_id):
            batch = production.x_manufacturing_batch_id
            if batch.production_group_id != production.production_group_id:
                batch.production_group_id = production.production_group_id
            if not batch.origin_production_id:
                batch.origin_production_id = production
            if not batch.route_id and production.x_process_route_id:
                batch._sync_from_production(production)
        return result

    def write(self, vals):
        result = super().write(vals)
        if {'product_id', 'product_uom_id', 'bom_id', 'x_process_route_id'}.intersection(vals):
            for production in self.filtered('x_manufacturing_batch_id'):
                if production.state not in ('draft', 'confirmed'):
                    continue
                batch = production.x_manufacturing_batch_id
                if batch.origin_production_id == production:
                    batch._sync_from_production(production)
        return result

    @api.constrains('x_manufacturing_batch_id', 'company_id', 'product_id')
    def _check_manufacturing_batch_scope(self):
        for production in self.filtered('x_manufacturing_batch_id'):
            batch = production.x_manufacturing_batch_id
            if batch.company_id != production.company_id:
                raise ValidationError(_('The manufacturing batch must belong to the same company as the manufacturing order.'))
            if batch.product_id != production.product_id:
                raise ValidationError(_('The manufacturing batch product must match the manufacturing order product.'))
