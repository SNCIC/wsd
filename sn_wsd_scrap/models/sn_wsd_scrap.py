from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SnWsdScrapReason(models.Model):
    _name = 'sn.wsd.scrap.reason'
    _description = 'SN WSD Scrap Reason'
    _order = 'code, id'
    _check_company_auto = True

    code = fields.Char(string='Reason Code', required=True, index=True)
    name = fields.Char(string='Reason Description', required=True)
    category = fields.Selection(
        [
            ('material', 'Material'),
            ('process', 'Process'),
            ('test', 'Test'),
            ('appearance', 'Appearance'),
            ('operation', 'Operation'),
            ('other', 'Other'),
        ],
        string='Reason Category',
        required=True,
        default='other',
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
        'The scrap reason code must be unique per company.',
    )


class SnWsdScrapRecord(models.Model):
    _name = 'sn.wsd.scrap.record'
    _description = 'SN WSD Scrap Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scrap_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Scrap Reference',
        required=True,
        copy=False,
        readonly=True,
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
    serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Scrap Product SN',
        required=True,
        index=True,
        check_company=True,
        tracking=True,
    )
    serial_no = fields.Char(string='SN', related='serial_id.serial_no', store=True, readonly=True)
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lot/Serial',
        check_company=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        related='serial_id.product_id',
        store=True,
        readonly=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
        index=True,
        check_company=True,
        tracking=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        index=True,
        check_company=True,
        tracking=True,
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Scrap Operation',
        required=True,
        index=True,
        check_company=True,
        tracking=True,
    )
    process_step_id = fields.Many2one(
        'sn.wsd.process.route.operation',
        string='Scrap Process Step',
        index=True,
        check_company=True,
        tracking=True,
    )
    scrap_reason_id = fields.Many2one(
        'sn.wsd.scrap.reason',
        string='Scrap Reason Code',
        required=True,
        index=True,
        check_company=True,
        tracking=True,
    )
    quality_issue_id = fields.Many2one(
        'sn.wsd.quality.issue',
        string='Quality Issue',
        check_company=True,
        index=True,
    )
    scrap_qty = fields.Float(string='Scrap Quantity', required=True, default=1.0, tracking=True)
    scrap_time = fields.Datetime(string='Scrap Time', default=fields.Datetime.now, required=True, index=True, tracking=True)
    scrap_user_id = fields.Many2one('res.users', string='Scrap User', default=lambda self: self.env.user, required=True, tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('scrapped', 'Scrapped'), ('restored', 'Restored')],
        string='Status',
        required=True,
        default='draft',
        index=True,
        tracking=True,
    )
    stock_scrap_id = fields.Many2one('stock.scrap', string='Stock Scrap', readonly=True, copy=False, check_company=True)
    restore_move_id = fields.Many2one('stock.move', string='Restore Move', readonly=True, copy=False, check_company=True)
    workorder_report_id = fields.Many2one(
        'mrp.workorder.report',
        string='Workorder Report',
        readonly=True,
        copy=False,
        check_company=True,
    )
    restore_time = fields.Datetime(string='Restore Time', readonly=True, copy=False, tracking=True)
    restore_user_id = fields.Many2one('res.users', string='Restore User', readonly=True, copy=False, tracking=True)
    resume_workorder_id = fields.Many2one('mrp.workorder', string='Resume Work Order', readonly=True, copy=False, check_company=True)
    note = fields.Text(string='Notes')
    previous_meter_state = fields.Char(
        string='Previous Meter State',
        readonly=True,
        copy=False,
    )
    previous_final_result = fields.Selection(
        selection=lambda self: self.env['sn.wsd.internal.serial']._fields['final_result'].selection,
        string='Previous Final Result',
        readonly=True,
        copy=False,
    )
    previous_workorder_id = fields.Many2one('mrp.workorder', string='Previous Work Order', readonly=True, copy=False, check_company=True)
    previous_quality_hold_state = fields.Selection(
        selection=lambda self: self.env['sn.wsd.internal.serial']._fields['x_quality_hold_state'].selection,
        string='Previous Quality Hold State',
        readonly=True,
        copy=False,
    )
    previous_issue_state = fields.Selection(
        selection=lambda self: self.env['sn.wsd.quality.issue']._fields['state'].selection,
        string='Previous Issue State',
        readonly=True,
        copy=False,
    )
    previous_issue_disposition = fields.Selection(
        selection=lambda self: self.env['sn.wsd.quality.issue']._fields['disposition'].selection,
        string='Previous Issue Disposition',
        readonly=True,
        copy=False,
    )
    production_qty = fields.Float(string='Input Quantity', related='production_id.product_qty', store=True, readonly=True)
    output_qty = fields.Float(string='Output Quantity', compute='_compute_qty_metrics')
    balance_qty = fields.Float(string='Input - Output - Scrap', compute='_compute_qty_metrics')
    scrap_rate = fields.Float(string='Scrap Rate (%)', compute='_compute_qty_metrics')

    @api.depends('production_id.product_qty', 'production_id.qty_produced', 'scrap_qty', 'state')
    def _compute_qty_metrics(self):
        for record in self:
            output_qty = record.production_id.qty_produced if record.production_id else 0.0
            active_scrap_qty = record.scrap_qty if record.state == 'scrapped' else 0.0
            input_qty = record.production_id.product_qty if record.production_id else 0.0
            record.output_qty = output_qty
            record.balance_qty = input_qty - output_qty - active_scrap_qty
            record.scrap_rate = (active_scrap_qty / input_qty * 100.0) if input_qty else 0.0

    @api.onchange('serial_id')
    def _onchange_serial_id(self):
        for record in self:
            serial = record.serial_id
            if not serial:
                continue
            record.lot_id = False
            record.production_id = serial.production_id
            record.workorder_id = serial.current_workorder_id
            record.process_step_id = serial.current_workorder_id.x_route_operation_id
            if serial.product_id and serial.product_id.tracking == 'serial':
                record.scrap_qty = 1.0

    @api.onchange('workorder_id')
    def _onchange_workorder_id(self):
        for record in self:
            if record.workorder_id:
                record.production_id = record.workorder_id.production_id
                record.process_step_id = record.workorder_id.x_route_operation_id

    @api.constrains('scrap_qty', 'serial_id')
    def _check_scrap_qty(self):
        for record in self:
            if record.scrap_qty <= 0:
                raise ValidationError(_('The scrap quantity must be positive.'))
            if record.serial_id and record.product_id.tracking == 'serial' and record.scrap_qty != 1.0:
                raise ValidationError(_('Serial-tracked scrap records must use quantity 1.'))

    @api.constrains('workorder_id', 'production_id')
    def _check_workorder_matches_production(self):
        for record in self:
            if record.workorder_id and record.production_id and record.workorder_id.production_id != record.production_id:
                raise ValidationError(_('The selected work order must belong to the selected manufacturing order.'))

    @api.constrains('serial_id', 'state')
    def _check_single_active_scrap_per_serial(self):
        for record in self.filtered(lambda item: item.serial_id and item.state == 'scrapped'):
            duplicate = self.search_count([
                ('id', '!=', record.id),
                ('serial_id', '=', record.serial_id.id),
                ('state', '=', 'scrapped'),
            ])
            if duplicate:
                raise ValidationError(_('Each SN can only have one active scrap record.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.scrap.record') or _('New')
            if not vals.get('mes_order_id'):
                serial = self.env['sn.wsd.internal.serial'].browse(vals.get('serial_id')).exists() if vals.get('serial_id') else self.env['sn.wsd.internal.serial']
                workorder = self.env['mrp.workorder'].browse(vals.get('workorder_id')).exists() if vals.get('workorder_id') else serial.current_workorder_id
                production = self.env['mrp.production'].browse(vals.get('production_id')).exists() if vals.get('production_id') else serial.production_id or workorder.production_id
                mes_order = serial.mes_order_id or workorder.x_mes_order_id or production.x_mes_order_id
                if mes_order:
                    vals['mes_order_id'] = mes_order.id
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('allow_scrap_record_write'):
            protected_fields = set(vals) - {'message_follower_ids', 'activity_ids'}
            if any(record.state != 'draft' for record in self) and protected_fields:
                raise UserError(_('Confirmed or restored scrap records cannot be modified.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(record.state != 'draft' for record in self):
            raise UserError(_('Scrap records cannot be deleted after confirmation.'))

    def _prepare_stock_scrap_vals(self):
        self.ensure_one()
        return {
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_id.uom_id.id,
            'lot_id': self.lot_id.id,
            'production_id': self.production_id.id,
            'workorder_id': self.workorder_id.id,
            'scrap_qty': self.scrap_qty,
            'origin': self.production_id.name or self.name,
        }

    def _prepare_restore_move_vals(self):
        self.ensure_one()
        stock_scrap = self.stock_scrap_id
        if not stock_scrap:
            raise UserError(_('The scrap record has no linked stock scrap document.'))
        return {
            'origin': self.name,
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom': self.product_id.uom_id.id,
            'product_uom_qty': self.scrap_qty,
            'location_id': stock_scrap.scrap_location_id.id,
            'location_dest_id': stock_scrap.location_id.id,
            'picked': True,
            'move_line_ids': [
                Command.create({
                    'product_id': self.product_id.id,
                    'product_uom_id': self.product_id.uom_id.id,
                    'quantity': self.scrap_qty,
                    'location_id': stock_scrap.scrap_location_id.id,
                    'location_dest_id': stock_scrap.location_id.id,
                    'lot_id': self.lot_id.id,
                })
            ],
        }

    def action_confirm_scrap(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft scrap records can be confirmed.'))
            existing = self.search([
                ('serial_id', '=', record.serial_id.id),
                ('state', '=', 'scrapped'),
                ('id', '!=', record.id),
            ], limit=1)
            if existing:
                raise UserError(_('This SN already has an active scrap record.'))
            stock_scrap = self.env['stock.scrap'].create(record._prepare_stock_scrap_vals())
            stock_scrap.action_validate()
            previous_issue_state = record.quality_issue_id.state if record.quality_issue_id else False
            previous_issue_disposition = record.quality_issue_id.disposition if record.quality_issue_id else False
            record.with_context(allow_scrap_record_write=True).write({
                'state': 'scrapped',
                'stock_scrap_id': stock_scrap.id,
                'scrap_time': record.scrap_time or fields.Datetime.now(),
                'scrap_user_id': record.scrap_user_id.id or self.env.user.id,
                'previous_meter_state': False,
                'previous_final_result': record.serial_id.final_result,
                'previous_workorder_id': record.serial_id.current_workorder_id.id,
                'previous_quality_hold_state': record.serial_id.x_quality_hold_state,
                'previous_issue_state': previous_issue_state,
                'previous_issue_disposition': previous_issue_disposition,
            })
            report = record.workorder_id.action_register_terminal_report(
                source_type='manual',
                report_type='complete',
                operator_code=record.scrap_user_id.login or self.env.user.login,
                external_event_id=f'SCRAP:{record.id}:CONFIRM',
                event_time=record.scrap_time,
                qty_in=record.scrap_qty,
                qty_ok=0.0,
                qty_ng=0.0,
                qty_scrap=record.scrap_qty,
                qty_repair=0.0,
                qty_rework=0.0,
                serial_no=record.serial_no,
                remark=record.note or _('Scrap confirmed by %s') % record.name,
            ) if record.workorder_id else self.env['mrp.workorder.report']
            if report:
                record.with_context(allow_scrap_record_write=True).write({
                    'workorder_report_id': report.id,
                })
            record.serial_id.write({
                'final_result': 'scrap',
                'x_quality_hold_state': 'scrapped',
                'current_workorder_id': record.workorder_id.id,
            })
            if record.quality_issue_id:
                record.quality_issue_id.write({
                    'scrap_record_id': record.id,
                    'state': 'scrapped',
                    'disposition': 'scrap',
                    'closed_time': fields.Datetime.now(),
                })
            if record.workorder_id:
                record.workorder_id.action_sync_meter_qty()
        return True

    def action_restore(self):
        for record in self:
            if record.state != 'scrapped':
                raise UserError(_('Only scrapped records can be restored.'))
            production = record.production_id or record.serial_id.production_id
            if production:
                production._lock_serial_capacity()
                capacity = production._get_serial_capacity()
                if capacity['active_serial_qty'] >= capacity['planned_qty']:
                    raise UserError(_(
                        'The scrapped SN cannot be restored because replacement serials already fill '
                        'the manufacturing order capacity. Planned: %(planned)s, active: %(active)s.'
                    ) % {
                        'planned': capacity['planned_qty'],
                        'active': capacity['active_serial_qty'],
                    })
            resume_workorder = record.workorder_id or record.previous_workorder_id
            move = self.env['stock.move'].create(record._prepare_restore_move_vals())
            move._action_done()
            record.serial_id.write({
                'final_result': record.previous_final_result or False,
                'x_quality_hold_state': record.previous_quality_hold_state or 'released',
                'current_workorder_id': resume_workorder.id,
            })
            if record.quality_issue_id:
                record.quality_issue_id.write({
                    'state': record.previous_issue_state or 'analysis',
                    'disposition': record.previous_issue_disposition or 'rework',
                    'closed_time': False,
                })
            record.with_context(allow_scrap_record_write=True).write({
                'state': 'restored',
                'restore_move_id': move.id,
                'workorder_report_id': record.workorder_report_id.id,
                'restore_time': fields.Datetime.now(),
                'restore_user_id': self.env.user.id,
                'resume_workorder_id': resume_workorder.id,
            })
            if record.workorder_report_id and record.workorder_report_id.state != 'cancelled':
                record.workorder_report_id.action_cancel()
            if resume_workorder:
                if resume_workorder.state in ('pending', 'done', 'cancel'):
                    resume_workorder.state = 'ready'
                resume_workorder.action_sync_meter_qty()
        return True

    def action_restore_and_resume_flow(self):
        self.ensure_one()
        if self.state == 'scrapped':
            self.action_restore()
        if self.state != 'restored':
            raise UserError(_('Only restored scrap records can resume flow.'))
        workorder = self.resume_workorder_id or self.workorder_id or self.previous_workorder_id
        if not workorder:
            raise UserError(_('There is no work order available to resume the flow.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Resume Scrap Flow'),
            'res_model': 'sn.wsd.workorder.terminal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_workorder_id': workorder.id,
                'default_workcenter_id': workorder.x_mes_workcenter_id.id,
                'default_mode': 'manual',
                'default_report_type': 'start',
                'default_serial_no': self.serial_no,
                'default_operator_code': self.scrap_user_id.login or False,
                'default_remark': _('Resume from scrap record %s') % self.name,
                'default_qty_in': 1.0,
            },
        }

    def action_open_stock_scrap(self):
        self.ensure_one()
        if not self.stock_scrap_id:
            raise UserError(_('There is no linked stock scrap document yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock Scrap'),
            'res_model': 'stock.scrap',
            'view_mode': 'form',
            'res_id': self.stock_scrap_id.id,
        }


class InternalSerial(models.Model):
    _inherit = 'sn.wsd.internal.serial'

    scrap_record_ids = fields.One2many('sn.wsd.scrap.record', 'serial_id', string='Scrap Records', readonly=True)
    scrap_record_count = fields.Integer(string='Scrap Record Count', compute='_compute_scrap_record_count')

    def _compute_scrap_record_count(self):
        for record in self:
            record.scrap_record_count = len(record.scrap_record_ids)

    def action_open_scrap_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scrap Records'),
            'res_model': 'sn.wsd.scrap.record',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('serial_id', '=', self.id)],
            'context': {
                'default_serial_id': self.id,
                'default_workorder_id': self.current_workorder_id.id,
                'default_production_id': self.production_id.id,
                'default_process_step_id': self.current_workorder_id.x_route_operation_id.id,
            },
        }

    def action_create_scrap_record(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Scrap Record'),
            'res_model': 'sn.wsd.scrap.record',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_serial_id': self.id,
                'default_workorder_id': self.current_workorder_id.id,
                'default_production_id': self.production_id.id,
                'default_process_step_id': self.current_workorder_id.x_route_operation_id.id,
                'default_scrap_user_id': self.env.user.id,
                'default_scrap_qty': 1.0,
            },
        }


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_scrap_record_ids = fields.One2many('sn.wsd.scrap.record', 'production_id', string='Scrap Records', readonly=True)
    x_scrap_record_count = fields.Integer(string='Scrap Record Count', compute='_compute_x_scrap_summary')
    x_scrap_qty_total = fields.Float(string='Scrap Quantity', compute='_compute_x_scrap_summary')
    x_qty_equation_balance = fields.Float(string='Input - Output - Scrap', compute='_compute_x_scrap_summary')

    def _compute_x_scrap_summary(self):
        for production in self:
            active_records = production.x_scrap_record_ids.filtered(lambda item: item.state == 'scrapped')
            production.x_scrap_record_count = len(production.x_scrap_record_ids)
            production.x_scrap_qty_total = sum(active_records.mapped('scrap_qty'))
            production.x_qty_equation_balance = production.product_qty - production.qty_produced - production.x_scrap_qty_total

    def action_open_scrap_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scrap Records'),
            'res_model': 'sn.wsd.scrap.record',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('production_id', '=', self.id)],
            'context': {
                'default_production_id': self.id,
                'search_default_group_by_reason': 1,
            },
        }


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    x_scrap_record_ids = fields.One2many('sn.wsd.scrap.record', 'workorder_id', string='Scrap Records', readonly=True)
    x_scrap_record_count = fields.Integer(string='Scrap Record Count', compute='_compute_x_scrap_record_summary')
    x_scrap_qty_total = fields.Float(string='Scrap Quantity', compute='_compute_x_scrap_record_summary')

    def _compute_x_scrap_record_summary(self):
        for workorder in self:
            active_records = workorder.x_scrap_record_ids.filtered(lambda item: item.state == 'scrapped')
            workorder.x_scrap_record_count = len(workorder.x_scrap_record_ids)
            workorder.x_scrap_qty_total = sum(active_records.mapped('scrap_qty'))

    def action_open_scrap_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scrap Records'),
            'res_model': 'sn.wsd.scrap.record',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('workorder_id', '=', self.id)],
            'context': {
                'default_workorder_id': self.id,
                'default_production_id': self.production_id.id,
                'default_process_step_id': self.x_route_operation_id.id,
            },
        }

    def action_create_scrap_record(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Scrap Record'),
            'res_model': 'sn.wsd.scrap.record',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_workorder_id': self.id,
                'default_production_id': self.production_id.id,
                'default_process_step_id': self.x_route_operation_id.id,
                'default_scrap_user_id': self.env.user.id,
                'default_scrap_qty': 1.0,
            },
        }


class MeterQualityIssue(models.Model):
    _inherit = 'sn.wsd.quality.issue'

    scrap_record_id = fields.Many2one('sn.wsd.scrap.record', string='Scrap Record', readonly=True, copy=False, check_company=True)
    scrap_record_ids = fields.One2many('sn.wsd.scrap.record', 'quality_issue_id', string='Scrap Records', readonly=True)
    active_scrap_record_id = fields.Many2one(
        'sn.wsd.scrap.record',
        string='Active Scrap Record',
        compute='_compute_scrap_record_summary',
    )
    restored_scrap_record_ids = fields.One2many(
        'sn.wsd.scrap.record',
        string='Restored Scrap Records',
        compute='_compute_scrap_record_summary',
    )
    scrap_record_count = fields.Integer(string='Scrap Record Count', compute='_compute_scrap_record_summary')
    restored_scrap_record_count = fields.Integer(string='Restored Scrap Record Count', compute='_compute_scrap_record_summary')

    @api.depends('scrap_record_ids.state')
    def _compute_scrap_record_summary(self):
        for issue in self:
            restored_records = issue.scrap_record_ids.filtered(lambda record: record.state == 'restored')
            active_record = issue.scrap_record_ids.filtered(lambda record: record.state == 'scrapped')[:1]
            issue.scrap_record_count = len(issue.scrap_record_ids)
            issue.restored_scrap_record_count = len(restored_records)
            issue.active_scrap_record_id = active_record
            issue.restored_scrap_record_ids = restored_records

    def action_open_scrap_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scrap Records'),
            'res_model': 'sn.wsd.scrap.record',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('quality_issue_id', '=', self.id)],
            'context': {
                'default_quality_issue_id': self.id,
                'default_serial_id': self.internal_serial_id.id,
                'default_workorder_id': self.workorder_id.id or self.internal_serial_id.current_workorder_id.id,
                'default_production_id': self.production_id.id or self.internal_serial_id.production_id.id,
            },
        }

    def action_scrap(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Scrap Record'),
            'res_model': 'sn.wsd.scrap.record',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_serial_id': self.internal_serial_id.id,
                'default_workorder_id': self.workorder_id.id or self.internal_serial_id.current_workorder_id.id,
                'default_production_id': self.production_id.id or self.internal_serial_id.production_id.id,
                'default_process_step_id': self.workorder_id.x_route_operation_id.id if self.workorder_id else self.internal_serial_id.current_workorder_id.x_route_operation_id.id,
                'default_quality_issue_id': self.id,
                'default_scrap_user_id': self.env.user.id,
                'default_scrap_qty': 1.0,
                'default_note': self.note,
            },
        }

