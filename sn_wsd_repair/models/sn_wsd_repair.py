from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SnWsdRepairType(models.Model):
    _name = 'sn.wsd.repair.type'
    _description = 'SN WSD Repair Type'
    _order = 'code, id'
    _check_company_auto = True

    name = fields.Char(string='Repair Type', required=True)
    code = fields.Char(string='Type Code', required=True, index=True)
    mode = fields.Selection(
        [('sn', 'SN Pass Repair'), ('qty', 'Quantity Repair')],
        string='Repair Mode',
        required=True,
        default='sn',
        index=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    note = fields.Text(string='Notes')

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The repair type code must be unique per company.',
    )


class SnWsdRepairOrder(models.Model):
    _name = 'sn.wsd.repair.order'
    _description = 'SN WSD Repair Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'reported_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Repair Reference',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    repair_type_id = fields.Many2one(
        'sn.wsd.repair.type',
        string='Repair Type',
        required=True,
        check_company=True,
        tracking=True,
    )
    repair_mode = fields.Selection(
        related='repair_type_id.mode',
        string='Repair Mode',
        store=True,
        readonly=True,
        index=True,
    )
    serial_no = fields.Char(string='Scanned SN', index=True, tracking=True)
    serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Product SN',
        check_company=True,
        index=True,
        tracking=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        compute='_compute_product_context',
        store=True,
        readonly=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        check_company=True,
        index=True,
        tracking=True,
    )
    manufacturing_batch_id = fields.Many2one(
        'sn.wsd.manufacturing.batch',
        string='Manufacturing Batch',
        check_company=True,
        index=True,
        tracking=True,
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Repair Source Work Order',
        check_company=True,
        index=True,
        tracking=True,
    )
    current_process_step_id = fields.Many2one(
        'sn.wsd.process.route.operation',
        string='Source Process Step',
        check_company=True,
        index=True,
    )
    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code',
        string='Defect Code',
        required=True,
        check_company=True,
        index=True,
        tracking=True,
    )
    quality_issue_id = fields.Many2one(
        'sn.wsd.quality.issue',
        string='Quality Issue',
        check_company=True,
        index=True,
    )
    repair_method = fields.Text(string='Repair Method', tracking=True)
    replacement_sn = fields.Char(string='Replacement Material SN', index=True)
    board_sn = fields.Char(string='Board SN', index=True)
    defect_qty = fields.Float(string='Defect Quantity', digits='Product Unit', tracking=True)
    repair_qty = fields.Float(string='Repair Quantity', digits='Product Unit', default=1.0, tracking=True)
    reported_time = fields.Datetime(string='Reported Time', default=fields.Datetime.now, required=True, index=True, tracking=True)
    reported_user_id = fields.Many2one('res.users', string='Reported By', default=lambda self: self.env.user, required=True, tracking=True)
    repair_user_id = fields.Many2one('res.users', string='Repair User', default=lambda self: self.env.user, tracking=True)
    repair_time = fields.Datetime(string='Repair Time', tracking=True)
    repair_process_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Repair Process Route',
        related='production_id.x_route_id',
        readonly=True,
    )
    repair_entry_step_id = fields.Many2one(
        'sn.wsd.process.route.operation',
        string='Repair Entry Step',
        check_company=True,
        domain="[('route_id', '=', repair_process_route_id)]",
        tracking=True,
    )
    result = fields.Selection(
        [('ok', 'Repair OK'), ('scrap', 'Repair Invalid Scrap')],
        string='Repair Result',
        tracking=True,
    )
    scrap_reason_id = fields.Many2one(
        'sn.wsd.scrap.reason',
        string='Scrap Reason',
        check_company=True,
    )
    scrap_record_id = fields.Many2one(
        'sn.wsd.scrap.record',
        string='Scrap Record',
        check_company=True,
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('reported', 'Reported'),
            ('repairing', 'Repairing'),
            ('done', 'Done'),
            ('scrapped', 'Scrapped'),
            ('cancel', 'Cancelled'),
        ],
        string='Status',
        required=True,
        default='draft',
        index=True,
        tracking=True,
    )
    note = fields.Text(string='Notes')

    def _get_report_event_id(self, event_type):
        self.ensure_one()
        return f'REPAIR:{self.id}:{event_type}'

    def _register_qty_rework_report(self):
        self.ensure_one()
        if self.repair_mode != 'qty' or not self.workorder_id:
            return self.env['mrp.workorder.report']
        return self.workorder_id.action_register_terminal_report(
            source_type='manual',
            report_type='complete',
            operator_code=self.reported_user_id.login or self.repair_user_id.login or self.env.user.login,
            external_event_id=self._get_report_event_id('reported'),
            event_time=self.reported_time or fields.Datetime.now(),
            qty_in=self.repair_qty,
            qty_ok=0.0,
            qty_ng=0.0,
            qty_scrap=0.0,
            qty_repair=0.0,
            qty_rework=self.repair_qty,
            remark=self.note or _('Repair order %s reported quantity rework') % self.name,
        )

    @api.depends('serial_id', 'serial_id.product_id', 'production_id.product_id')
    def _compute_product_context(self):
        for record in self:
            record.product_id = record.serial_id.product_id or record.production_id.product_id

    def _get_serial_manufacturing_context(self, serial):
        workorder = serial.current_workorder_id
        production = workorder.production_id or serial.current_production_id or serial.production_id
        manufacturing_batch = (
            serial.manufacturing_batch_id
            or workorder.x_manufacturing_batch_id
            or production.x_manufacturing_batch_id
        )
        return {
            'serial_id': serial,
            'production_id': production,
            'manufacturing_batch_id': manufacturing_batch,
            'workorder_id': workorder,
            'current_process_step_id': workorder.x_route_operation_id,
        }

    def _apply_serial_manufacturing_context(self, serial):
        self.ensure_one()
        context_values = self._get_serial_manufacturing_context(serial)
        for field_name, value in context_values.items():
            self[field_name] = value

    @api.onchange('serial_no')
    def _onchange_serial_no(self):
        for record in self:
            if record.repair_mode == 'qty':
                continue
            record.serial_no = (record.serial_no or '').strip()
            serial = record._find_serial_by_no(record.serial_no)
            record._apply_serial_manufacturing_context(serial)
            if record.serial_no and not serial:
                return {
                    'warning': {
                        'title': _('Scanned SN'),
                        'message': _('The scanned SN does not exist.'),
                        'type': 'notification',
                    },
                }

    @api.onchange('serial_id')
    def _onchange_serial_id(self):
        for record in self:
            serial = record.serial_id
            if not serial:
                continue
            record.serial_no = serial.serial_no
            record._apply_serial_manufacturing_context(serial)
            if not record.defect_qty:
                record.defect_qty = 1.0
            if not record.repair_qty:
                record.repair_qty = 1.0

    @api.onchange('workorder_id')
    def _onchange_workorder_id(self):
        for record in self:
            if not record.workorder_id:
                continue
            record.production_id = record.workorder_id.production_id
            record.manufacturing_batch_id = record.workorder_id.x_manufacturing_batch_id
            record.current_process_step_id = record.workorder_id.x_route_operation_id
            if record.repair_entry_step_id and record.repair_entry_step_id.route_id != record.production_id.x_route_id:
                record.repair_entry_step_id = False
            if record.repair_mode == 'qty' and not record.defect_qty:
                record.defect_qty = record.workorder_id.x_meter_qty_fail

    @api.onchange('production_id')
    def _onchange_production_id_repair_entry_step(self):
        for record in self:
            if (
                record.repair_entry_step_id
                and record.production_id
                and record.repair_entry_step_id.route_id != record.production_id.x_route_id
            ):
                record.repair_entry_step_id = False

    @api.constrains('repair_mode', 'serial_id', 'replacement_sn', 'board_sn')
    def _check_mode_serial_fields(self):
        for record in self:
            if record.repair_mode == 'sn' and not record.serial_id:
                raise ValidationError(_('SN pass repair must record a product SN.'))
            if record.repair_mode == 'qty' and (record.serial_id or record.serial_no or record.replacement_sn or record.board_sn):
                raise ValidationError(_('Quantity repair must not record product SN, replacement SN, or board SN.'))

    @api.constrains('repair_qty', 'defect_qty', 'repair_mode')
    def _check_repair_quantity(self):
        for record in self:
            if record.repair_qty <= 0:
                raise ValidationError(_('The repair quantity must be positive.'))
            if record.defect_qty < 0:
                raise ValidationError(_('The defect quantity cannot be negative.'))
            if record.repair_mode == 'qty' and record.repair_qty > record.defect_qty:
                raise ValidationError(_('The repair quantity must be less than or equal to the defect quantity.'))
            if record.repair_mode == 'sn' and record.repair_qty != 1.0:
                raise ValidationError(_('SN pass repair quantity must be 1.'))

    @api.constrains('workorder_id', 'production_id')
    def _check_workorder_matches_production(self):
        for record in self:
            if record.workorder_id and record.production_id and record.workorder_id.production_id != record.production_id:
                raise ValidationError(_('The selected work order must belong to the selected manufacturing order.'))

    @api.constrains('production_id', 'repair_entry_step_id')
    def _check_repair_entry_step(self):
        for record in self:
            if (
                record.repair_entry_step_id
                and record.production_id
                and record.repair_entry_step_id.route_id != record.production_id.x_route_id
            ):
                raise ValidationError(_('The repair entry step must belong to the manufacturing order route.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.repair.order') or _('New')
            if not vals.get('manufacturing_batch_id'):
                serial = self.env['sn.wsd.internal.serial'].browse(vals.get('serial_id')).exists() if vals.get('serial_id') else self.env['sn.wsd.internal.serial']
                workorder = self.env['mrp.workorder'].browse(vals.get('workorder_id')).exists() if vals.get('workorder_id') else serial.current_workorder_id
                production = self.env['mrp.production'].browse(vals.get('production_id')).exists() if vals.get('production_id') else serial.production_id or workorder.production_id
                batch = serial.manufacturing_batch_id or workorder.x_manufacturing_batch_id or production.x_manufacturing_batch_id
                if batch:
                    vals['manufacturing_batch_id'] = batch.id
            repair_type = self.env['sn.wsd.repair.type'].browse(vals.get('repair_type_id'))
            if repair_type.mode == 'qty':
                vals['serial_id'] = False
                vals['serial_no'] = False
                vals['replacement_sn'] = False
                vals['board_sn'] = False
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('allow_repair_order_write'):
            protected_fields = set(vals) - {'message_follower_ids', 'activity_ids'}
            if protected_fields and any(record.state in ('done', 'scrapped', 'cancel') for record in self):
                raise UserError(_('Finished repair orders cannot be modified.'))
        if vals.get('repair_type_id'):
            repair_type = self.env['sn.wsd.repair.type'].browse(vals['repair_type_id'])
            if repair_type.mode == 'qty':
                vals = {**vals, 'serial_id': False, 'serial_no': False, 'replacement_sn': False, 'board_sn': False}
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(record.state != 'draft' for record in self):
            raise UserError(_('Only draft repair orders can be deleted.'))

    @api.model
    def _find_serial_by_no(self, serial_no):
        serial_no = (serial_no or '').strip()
        if not serial_no:
            return self.env['sn.wsd.internal.serial']
        company = self.company_id or self.env.company
        serial_model = self.env['sn.wsd.internal.serial']
        base_domain = [('company_id', '=', company.id)]
        serial = serial_model.search(
            base_domain + [('serial_no', '=', serial_no)],
            order='production_date desc, id desc',
            limit=1,
        )
        if serial:
            return serial
        return serial_model.search(
            base_domain + [('barcode', '=', serial_no)],
            order='production_date desc, id desc',
            limit=1,
        )

    def _serial_is_repairable(self):
        self.ensure_one()
        serial = self.serial_id
        if not serial:
            return False
        if serial.state == 'scrapped':
            return False
        if serial.state == 'rework' or serial.final_result in ('fail', 'hold'):
            return True
        if serial.x_quality_hold_state in ('hold', 'blocked'):
            return True
        return bool(serial.quality_issue_ids.filtered(lambda issue: issue.state not in ('closed', 'scrapped')))

    def _ensure_reportable(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft repair orders can be reported.'))
            if record.repair_mode == 'sn':
                if not record.serial_id and record.serial_no:
                    record.serial_id = record._find_serial_by_no(record.serial_no)
                if not record.serial_id:
                    raise UserError(_('The scanned SN does not exist.'))
                if not record._serial_is_repairable():
                    raise UserError(_('The scanned SN must be in abnormal or defective status before repair reporting.'))
                context_values = record._get_serial_manufacturing_context(record.serial_id)
                record.write({field_name: value.id for field_name, value in context_values.items()})
            else:
                if not record.workorder_id:
                    raise UserError(_('Quantity repair must be linked to the current work order.'))
                if not record.manufacturing_batch_id:
                    record.manufacturing_batch_id = record.workorder_id.x_manufacturing_batch_id
                if record.repair_qty > record.defect_qty:
                    raise UserError(_('The repair quantity must be less than or equal to the defect quantity.'))

    def _ensure_quality_issue(self):
        self.ensure_one()
        if self.quality_issue_id or self.repair_mode != 'sn':
            return
        issue = self.env['sn.wsd.quality.issue'].create({
            'internal_serial_id': self.serial_id.id,
            'workorder_id': self.workorder_id.id,
            'workcenter_id': self.workorder_id.x_mes_workcenter_id.id if self.workorder_id else False,
            'defect_code_id': self.defect_code_id.id,
            'issue_source': 'repair',
            'state': 'repairing',
            'detected_time': self.reported_time,
            'repair_action': self.repair_method,
            'responsible_user_id': self.repair_user_id.id,
            'note': self.note,
        })
        self.quality_issue_id = issue

    def _get_repair_entry_workorder(self):
        self.ensure_one()
        step = self.repair_entry_step_id
        if not step or not self.production_id:
            return self.env['mrp.workorder']
        productions = self.manufacturing_batch_id.production_ids if self.manufacturing_batch_id else self.production_id
        return productions.mapped('workorder_ids').filtered(lambda workorder: workorder.x_route_operation_id == step)[:1]

    def _get_repair_entry_workorder_or_raise(self):
        self.ensure_one()
        if not self.repair_entry_step_id:
            raise UserError(_('Select a repair entry step before starting repair.'))
        workorder = self._get_repair_entry_workorder()
        if not workorder:
            raise UserError(_('No manufacturing work order was found for the selected repair entry step.'))
        return workorder

    def action_report_repair(self):
        self._ensure_reportable()
        for record in self:
            vals = {
                'state': 'reported',
                'reported_time': record.reported_time or fields.Datetime.now(),
                'reported_user_id': record.reported_user_id.id or self.env.user.id,
            }
            record.with_context(allow_repair_order_write=True).write(vals)
            record._ensure_quality_issue()
            if record.repair_mode == 'qty':
                record._register_qty_rework_report()
        return True

    def action_start_repair(self):
        for record in self:
            if record.state != 'reported':
                raise UserError(_('Only reported repair orders can start repair.'))
            workorder = record._get_repair_entry_workorder_or_raise()
            if record.repair_mode == 'sn':
                record.serial_id.write({
                    'state': 'rework',
                    'final_result': 'fail',
                    'x_quality_hold_state': 'hold',
                    'current_workorder_id': workorder.id,
                })
                record.serial_id._mark_rework_started(workorder, source_workorder=record.workorder_id)
            record.with_context(allow_repair_order_write=True).write({'state': 'repairing'})
        return True

    def action_repair_ok(self):
        for record in self:
            if record.state != 'repairing':
                raise UserError(_('Only repairing orders can be marked as repair OK.'))
            vals = {
                'state': 'done',
                'result': 'ok',
                'repair_time': fields.Datetime.now(),
                'repair_user_id': record.repair_user_id.id or self.env.user.id,
            }
            record.with_context(allow_repair_order_write=True).write(vals)
            if record.repair_mode == 'sn':
                workorder = record._get_repair_entry_workorder_or_raise()
                record.serial_id.write({
                    'state': 'rework',
                    'final_result': False,
                    'x_quality_hold_state': 'released',
                    'current_workorder_id': workorder.id,
                })
                if record.quality_issue_id:
                    record.quality_issue_id.write({
                        'state': 'closed',
                        'disposition': 'rework',
                        'repair_action': record.repair_method,
                        'responsible_user_id': record.repair_user_id.id,
                        'closed_time': record.repair_time,
                    })
        return True

    def action_repair_scrap(self):
        for record in self:
            if not record.scrap_reason_id:
                raise UserError(_('A scrap reason is required for invalid repair.'))
            if record.repair_mode != 'sn':
                raise UserError(_('Repair invalid scrap currently requires SN-level repair data.'))
            if record.state not in ('reported', 'repairing'):
                raise UserError(_('Only active repair orders can be scrapped.'))
            scrap = self.env['sn.wsd.scrap.record'].create({
                'serial_id': record.serial_id.id,
                'production_id': record.production_id.id,
                'workorder_id': record.workorder_id.id or record.serial_id.current_workorder_id.id,
                'process_step_id': record.current_process_step_id.id,
                'scrap_reason_id': record.scrap_reason_id.id,
                'quality_issue_id': record.quality_issue_id.id,
                'scrap_qty': 1.0,
                'scrap_user_id': record.repair_user_id.id or self.env.user.id,
                'note': _('Created from repair order %s') % record.name,
            })
            scrap.action_confirm_scrap()
            record.with_context(allow_repair_order_write=True).write({
                'state': 'scrapped',
                'result': 'scrap',
                'repair_time': fields.Datetime.now(),
                'repair_user_id': record.repair_user_id.id or self.env.user.id,
                'scrap_record_id': scrap.id,
            })
        return True

    def action_cancel(self):
        for record in self:
            if record.state in ('done', 'scrapped'):
                raise UserError(_('Finished repair orders cannot be cancelled.'))
            record.with_context(allow_repair_order_write=True).write({'state': 'cancel'})
        return True

class InternalSerial(models.Model):
    _inherit = 'sn.wsd.internal.serial'

    repair_order_ids = fields.One2many('sn.wsd.repair.order', 'serial_id', string='Repair Orders', readonly=True)
    repair_order_count = fields.Integer(string='Repair Order Count', compute='_compute_repair_order_count')

    def _compute_repair_order_count(self):
        for record in self:
            record.repair_order_count = len(record.repair_order_ids)

    def action_open_repair_orders(self):
        self.ensure_one()
        production = self.current_workorder_id.production_id or self.current_production_id or self.production_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Repair Orders'),
            'res_model': 'sn.wsd.repair.order',
            'view_mode': 'list,form',
            'domain': [('serial_id', '=', self.id)],
            'context': {
                'default_serial_id': self.id,
                'default_serial_no': self.serial_no,
                'default_production_id': production.id,
                'default_manufacturing_batch_id': self.manufacturing_batch_id.id,
                'default_workorder_id': self.current_workorder_id.id,
                'default_current_process_step_id': self.current_workorder_id.x_route_operation_id.id,
            },
        }

    def action_create_repair_order(self):
        self.ensure_one()
        production = self.current_workorder_id.production_id or self.current_production_id or self.production_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Repair Order'),
            'res_model': 'sn.wsd.repair.order',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_serial_id': self.id,
                'default_serial_no': self.serial_no,
                'default_production_id': production.id,
                'default_manufacturing_batch_id': self.manufacturing_batch_id.id,
                'default_workorder_id': self.current_workorder_id.id,
                'default_current_process_step_id': self.current_workorder_id.x_route_operation_id.id,
                'default_repair_qty': 1.0,
                'default_defect_qty': 1.0,
            },
        }


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_repair_order_ids = fields.One2many('sn.wsd.repair.order', 'production_id', string='Repair Orders', readonly=True)
    x_repair_order_count = fields.Integer(string='Repair Order Count', compute='_compute_x_repair_summary')
    x_repair_qty_total = fields.Float(string='Repair Quantity', compute='_compute_x_repair_summary')

    def _compute_x_repair_summary(self):
        for production in self:
            active_repairs = production.x_repair_order_ids.filtered(lambda item: item.state in ('done', 'scrapped'))
            production.x_repair_order_count = len(production.x_repair_order_ids)
            production.x_repair_qty_total = sum(active_repairs.mapped('repair_qty'))

    def action_open_repair_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Repair Orders'),
            'res_model': 'sn.wsd.repair.order',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id},
        }


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    x_repair_order_ids = fields.One2many('sn.wsd.repair.order', 'workorder_id', string='Repair Orders', readonly=True)
    x_repair_order_count = fields.Integer(string='Repair Order Count', compute='_compute_x_repair_summary')
    x_repair_qty_total = fields.Float(string='Repair Quantity', compute='_compute_x_repair_summary')

    def _compute_x_repair_summary(self):
        for workorder in self:
            active_repairs = workorder.x_repair_order_ids.filtered(lambda item: item.state in ('done', 'scrapped'))
            workorder.x_repair_order_count = len(workorder.x_repair_order_ids)
            workorder.x_repair_qty_total = sum(active_repairs.mapped('repair_qty'))

    def action_open_repair_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Repair Orders'),
            'res_model': 'sn.wsd.repair.order',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('workorder_id', '=', self.id)],
            'context': {
                'default_workorder_id': self.id,
                'default_production_id': self.production_id.id,
                'default_current_process_step_id': self.x_route_operation_id.id,
                'default_defect_qty': self.x_meter_qty_fail,
            },
        }


class MeterQualityIssue(models.Model):
    _inherit = 'sn.wsd.quality.issue'

    repair_order_ids = fields.One2many('sn.wsd.repair.order', 'quality_issue_id', string='Repair Orders', readonly=True)
    repair_order_count = fields.Integer(string='Repair Order Count', compute='_compute_repair_order_count')

    def _compute_repair_order_count(self):
        for record in self:
            record.repair_order_count = len(record.repair_order_ids)

    def action_open_repair_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Repair Orders'),
            'res_model': 'sn.wsd.repair.order',
            'view_mode': 'list,form',
            'domain': [('quality_issue_id', '=', self.id)],
            'context': {
                'default_quality_issue_id': self.id,
                'default_serial_id': self.internal_serial_id.id,
                'default_serial_no': self.internal_serial_id.serial_no,
                'default_production_id': self.production_id.id or self.internal_serial_id.production_id.id,
                'default_workorder_id': self.workorder_id.id or self.internal_serial_id.current_workorder_id.id,
                'default_defect_code_id': self.defect_code_id.id,
                'default_defect_qty': 1.0,
                'default_repair_qty': 1.0,
            },
        }
