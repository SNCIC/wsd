from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SnWsdRepairCause(models.Model):
    _name = 'sn.wsd.repair.cause'
    _description = 'SN WSD Repair Failure Cause'
    _order = 'code, id'
    _check_company_auto = True

    name = fields.Char(string='Failure Cause', required=True)
    code = fields.Char(string='Cause Code', required=True, index=True)
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
        'The failure cause code must be unique per company.',
    )
    _name_company_uniq = models.Constraint(
        'unique(company_id, name)',
        'The failure cause name must be unique per company.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = ' - '.join(
                part for part in (record.code, record.name) if part)

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        if name:
            domain = list(domain or []) + [
                '|', ('code', operator, name), ('name', operator, name)]
            return super().name_search('', domain=domain, operator='ilike', limit=limit)
        return super().name_search(name, domain=domain, operator=operator, limit=limit)


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
    repair_mode = fields.Selection(
        [('sn', 'SN Pass Repair'), ('qty', 'Quantity Repair')],
        string='Repair Mode',
        required=True,
        default='sn',
        index=True,
        tracking=True,
        help='Derived from the MES order management mode: station tracking -> '
             'SN pass repair, operation reporting -> quantity repair.',
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
        readonly=True,
        check_company=True,
        index=True,
        tracking=True,
        help='Traceability only: derived from the MES order. Business rules '
             'run on the MES order since process routes moved there.',
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        check_company=True,
        index=True,
        tracking=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Repair Source Route Operation',
        check_company=True,
        index=True,
        tracking=True,
    )
    repair_entry_route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Repair Entry Route Operation',
        check_company=True,
        index=True,
        tracking=True,
        help='MES order operation the SN flows back to after repair. '
             'Defaults to the operation where the defect was reported.',
    )
    current_process_step_id = fields.Many2one(
        related='route_operation_id.operation_id',
        string='Source Process Step',
        store=True,
        readonly=True,
        index=True,
    )
    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code',
        string='Defect Code',
        check_company=True,
        index=True,
        tracking=True,
        help='Main defect: derived from the defect line with the largest '
             'quantity; the defect lines are the source of truth.')
    defect_line_ids = fields.One2many(
        'sn.wsd.repair.order.line', 'repair_order_id', string='Defect Lines')
    quality_issue_id = fields.Many2one(
        'sn.wsd.quality.issue',
        string='Quality Issue',
        check_company=True,
        index=True,
    )
    repair_method = fields.Text(string='Repair Method', tracking=True)
    defect_location = fields.Char(
        string='Defect Location', index=True,
        help='Location of the defective component on the board, e.g. U12, R45.')
    failure_cause_id = fields.Many2one(
        'sn.wsd.repair.cause',
        string='Failure Cause',
        check_company=True,
        index=True,
    )
    replacement_sn = fields.Char(string='Replacement Material SN', index=True)
    replacement_product_id = fields.Many2one(
        'product.product',
        string='Replacement Product',
        check_company=True,
        index=True,
    )
    board_sn = fields.Char(string='Board SN', index=True)
    defect_qty = fields.Float(string='Defect Quantity', digits='Product Unit', tracking=True)
    repair_qty = fields.Float(string='Repair Quantity', digits='Product Unit', default=1.0, tracking=True)
    reported_time = fields.Datetime(string='Reported Time', default=fields.Datetime.now, required=True, index=True, tracking=True)
    reported_user_id = fields.Many2one('res.users', string='Reported By', default=lambda self: self.env.user, required=True, tracking=True)
    repair_user_id = fields.Many2one('res.users', string='Repair User', default=lambda self: self.env.user, tracking=True)
    repair_time = fields.Datetime(string='Repair Time', tracking=True)
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
        if self.repair_mode != 'qty' or not self.route_operation_id:
            return self.env['sn.wsd.mes.operation.report']
        if self.mes_order_id.x_manage_mode != 'report' or not self.mes_order_id.x_online_date:
            return self.env['sn.wsd.mes.operation.report']
        self.mes_order_id.report_operation_qty(
            self.route_operation_id,
            qty_ok=0.0,
            qty_ng=self.repair_qty,
            qty_scrap=0.0,
        )
        return self.env['sn.wsd.mes.operation.report'].search(
            [
                ('mes_order_id', '=', self.mes_order_id.id),
                ('route_operation_id', '=', self.route_operation_id.id),
            ],
            order='id desc',
            limit=1,
        )

    @api.depends('serial_id', 'serial_id.product_id', 'production_id.product_id')
    def _compute_product_context(self):
        for record in self:
            record.product_id = record.serial_id.product_id or record.production_id.product_id

    def _get_serial_manufacturing_context(self, serial):
        route_operation = serial.current_route_operation_id
        production = route_operation.mes_order_id.production_id or serial.current_production_id or serial.production_id
        mes_order = serial.mes_order_id or route_operation.mes_order_id or production.x_mes_order_ids[:1]
        return {
            'serial_id': serial,
            'production_id': production,
            'mes_order_id': mes_order,
            'route_operation_id': route_operation,
            'repair_entry_route_operation_id': route_operation,
            'repair_mode': 'qty' if mes_order.x_manage_mode == 'report' else 'sn',
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
            # Surface the SN's station defect history as defect lines: the
            # operator sees why the board was pulled before repairing.
            if not record.defect_line_ids:
                open_issues = serial.quality_issue_ids.filtered(
                    lambda issue: issue.state not in ('closed', 'scrapped') and issue.defect_code_id)
                if open_issues:
                    record.defect_line_ids = [
                        (0, 0, {'defect_code_id': issue.defect_code_id.id, 'qty': 1})
                        for issue in open_issues[:5]
                    ]
                    record.defect_code_id = open_issues[0].defect_code_id

    @api.onchange('route_operation_id')
    def _onchange_route_operation_id(self):
        for record in self:
            if not record.route_operation_id:
                continue
            record.production_id = record.route_operation_id.mes_order_id.production_id
            record.mes_order_id = record.route_operation_id.mes_order_id
            record.repair_mode = 'qty' if record.mes_order_id.x_manage_mode == 'report' else 'sn'
            # Inline rework defaults to flowing back where the defect occurred.
            if not record.repair_entry_route_operation_id or \
                    record.repair_entry_route_operation_id.mes_order_id != record.mes_order_id:
                record.repair_entry_route_operation_id = record.route_operation_id
            if record.repair_mode == 'qty' and not record.defect_qty:
                record.defect_qty = record.route_operation_id.x_ng_qty

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

    @api.onchange('defect_line_ids')
    def _onchange_defect_line_ids(self):
        lines = self.defect_line_ids.filtered(lambda line: line.defect_code_id)
        if not lines:
            return
        # Main defect = line with the largest quantity (first line breaks ties).
        main_line = max(lines, key=lambda line: line.qty)
        self.defect_code_id = main_line.defect_code_id
        if self.repair_mode == 'qty':
            total = sum(lines.mapped('qty'))
            if not self.defect_qty or self.defect_qty < total:
                self.defect_qty = total

    @api.constrains('defect_qty', 'defect_line_ids', 'repair_mode')
    def _check_defect_lines(self):
        for record in self:
            lines = record.defect_line_ids
            if not lines:
                continue
            if record.repair_mode == 'sn':
                for line in lines:
                    if line.qty != 1:
                        raise ValidationError(_('SN pass repair defect lines must have quantity 1.'))
            else:
                total = sum(lines.mapped('qty'))
                if total > record.defect_qty:
                    raise ValidationError(_(
                        'The defect line total (%s) exceeds the defect quantity (%s).',
                        total, record.defect_qty))

    @api.constrains('route_operation_id', 'mes_order_id')
    def _check_route_operation_matches_mes_order(self):
        for record in self:
            if (
                record.route_operation_id
                and record.mes_order_id
                and record.route_operation_id.mes_order_id != record.mes_order_id
            ):
                raise ValidationError(_('The defect operation must belong to the MES order.'))

    @api.constrains('repair_entry_route_operation_id', 'mes_order_id')
    def _check_repair_entry_route_operation(self):
        for record in self:
            if (
                record.repair_entry_route_operation_id
                and record.mes_order_id
                and record.repair_entry_route_operation_id.mes_order_id != record.mes_order_id
            ):
                raise ValidationError(_('The repair entry operation must belong to the MES order.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.repair.order') or _('New')
            if not vals.get('mes_order_id'):
                serial = self.env['sn.wsd.internal.serial'].browse(vals.get('serial_id')).exists() if vals.get('serial_id') else self.env['sn.wsd.internal.serial']
                route_operation = self.env['sn.wsd.mes.order.route.operation'].browse(vals.get('route_operation_id')).exists() if vals.get('route_operation_id') else serial.current_route_operation_id
                production = self.env['mrp.production'].browse(vals.get('production_id')).exists() if vals.get('production_id') else serial.production_id or route_operation.mes_order_id.production_id
                mes_order = serial.mes_order_id or route_operation.mes_order_id or production.x_mes_order_id
                if mes_order:
                    vals['mes_order_id'] = mes_order.id
            if vals.get('repair_mode') == 'qty':
                vals['serial_id'] = False
                vals['serial_no'] = False
                vals['replacement_sn'] = False
                vals['board_sn'] = False
            if vals.get('route_operation_id') and not vals.get('repair_entry_route_operation_id'):
                vals['repair_entry_route_operation_id'] = vals.get('route_operation_id')
            if not vals.get('repair_mode'):
                serial = self.env['sn.wsd.internal.serial'].browse(vals.get('serial_id')).exists()
                route_operation = self.env['sn.wsd.mes.order.route.operation'].browse(
                    vals.get('route_operation_id')).exists() if vals.get('route_operation_id') else serial.current_route_operation_id
                mes_order = (serial.mes_order_id or route_operation.mes_order_id) if (serial or route_operation) else self.env['sn.wsd.mes.order']
                vals['repair_mode'] = 'qty' if mes_order.x_manage_mode == 'report' else 'sn'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('allow_repair_order_write'):
            protected_fields = set(vals) - {'message_follower_ids', 'activity_ids'}
            if protected_fields and any(record.state in ('done', 'scrapped', 'cancel') for record in self):
                raise UserError(_('Finished repair orders cannot be modified.'))
        if vals.get('repair_mode') == 'qty':
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
        if serial.final_result in ('fail', 'hold'):
            return True
        if 'x_quality_hold_state' in serial._fields and serial.x_quality_hold_state in ('hold', 'blocked'):
            return True
        return bool(serial.quality_issue_ids.filtered(
            lambda issue: issue.state not in ('closed', 'scrapped')))

    def _ensure_reportable(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft repair orders can be reported.'))
            if not record.defect_line_ids:
                raise UserError(_('Add at least one defect line before reporting.'))
            if not record.defect_code_id:
                main_line = max(
                    record.defect_line_ids.filtered(lambda line: line.defect_code_id),
                    key=lambda line: line.qty,
                    default=self.env['sn.wsd.repair.order.line'],
                )
                if main_line:
                    record.defect_code_id = main_line.defect_code_id
            if record.repair_mode == 'sn':
                if not record.serial_id and record.serial_no:
                    record.serial_id = record._find_serial_by_no(record.serial_no)
                if not record.serial_id:
                    raise UserError(_('The scanned SN does not exist.'))
                if not record._serial_is_repairable():
                    raise UserError(_('The scanned SN must be in abnormal or defective status before repair reporting.'))
                context_values = record._get_serial_manufacturing_context(record.serial_id)
                entry = record.repair_entry_route_operation_id
                if entry and entry.mes_order_id == context_values['mes_order_id']:
                    context_values.pop('repair_entry_route_operation_id')
                record.write({
                    field_name: value.id if hasattr(value, 'id') and not isinstance(value, str) else value
                    for field_name, value in context_values.items()
                })
            else:
                if not record.route_operation_id:
                    raise UserError(_('Quantity repair must be linked to the current route operation.'))
                if not record.mes_order_id:
                    record.mes_order_id = record.route_operation_id.mes_order_id
                if record.repair_qty > record.defect_qty:
                    raise UserError(_('The repair quantity must be less than or equal to the defect quantity.'))

    def _ensure_quality_issue(self):
        self.ensure_one()
        if self.quality_issue_id or self.repair_mode != 'sn':
            return
        issue = self.env['sn.wsd.quality.issue'].create({
            'internal_serial_id': self.serial_id.id,
            'route_operation_id': self.route_operation_id.id,
            'workcenter_id': self.route_operation_id.workcenter_id.id if self.route_operation_id else False,
            'defect_code_id': self.defect_code_id.id,
            'issue_source': 'repair',
            'state': 'repairing',
            'detected_time': self.reported_time,
            'repair_action': self.repair_method,
            'responsible_user_id': self.repair_user_id.id,
            'note': self.note,
        })
        self.quality_issue_id = issue

    def _get_repair_entry_route_operation(self):
        self.ensure_one()
        return self.repair_entry_route_operation_id or self.route_operation_id

    def _get_repair_entry_route_operation_or_raise(self):
        self.ensure_one()
        route_operation = self._get_repair_entry_route_operation()
        if not route_operation:
            raise UserError(_('Select a repair entry operation before starting repair.'))
        return route_operation

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
            route_operation = record._get_repair_entry_route_operation_or_raise()
            if record.repair_mode == 'sn':
                serial_values = {
                    'final_result': 'fail',
                    'current_route_operation_id': route_operation.id,
                }
                if 'x_quality_hold_state' in record.serial_id._fields:
                    serial_values['x_quality_hold_state'] = 'hold'
                record.serial_id.write(serial_values)
                record.serial_id._mark_rework_started()
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
                route_operation = record._get_repair_entry_route_operation_or_raise()
                serial_values = {
                    'final_result': False,
                    'current_route_operation_id': route_operation.id,
                }
                if 'x_quality_hold_state' in record.serial_id._fields:
                    serial_values['x_quality_hold_state'] = 'released'
                record.serial_id.write(serial_values)
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
                'mes_order_id': record.mes_order_id.id,
                'route_operation_id': record.route_operation_id.id or record.serial_id.current_route_operation_id.id,
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
        production = self.current_route_operation_id.mes_order_id.production_id or self.current_production_id or self.production_id
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
                'default_mes_order_id': self.mes_order_id.id,
                'default_route_operation_id': self.current_route_operation_id.id,
                'default_current_process_step_id': self.current_route_operation_id.operation_id.id,
            },
        }

    def action_create_repair_order(self):
        self.ensure_one()
        production = self.current_route_operation_id.mes_order_id.production_id or self.current_production_id or self.production_id
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
                'default_mes_order_id': self.mes_order_id.id,
                'default_route_operation_id': self.current_route_operation_id.id,
                'default_current_process_step_id': self.current_route_operation_id.operation_id.id,
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
                'default_route_operation_id': self.route_operation_id.id or self.internal_serial_id.current_route_operation_id.id,
                'default_defect_code_id': self.defect_code_id.id,
                'default_defect_qty': 1.0,
                'default_repair_qty': 1.0,
            },
        }


class SnWsdRepairOrderLine(models.Model):
    _name = 'sn.wsd.repair.order.line'
    _description = 'SN WSD Repair Defect Line'
    _order = 'repair_order_id, sequence, id'

    repair_order_id = fields.Many2one(
        'sn.wsd.repair.order', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code',
        string='Defect Code',
        required=True,
        check_company=True,
        index=True,
    )
    qty = fields.Integer(string='Quantity', default=1, required=True)
    defect_location = fields.Char(string='Defect Location')
    repair_mode = fields.Selection(
        related='repair_order_id.repair_mode')
    company_id = fields.Many2one(
        'res.company', related='repair_order_id.company_id', store=True, index=True)
