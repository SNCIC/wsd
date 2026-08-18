from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


LASER_SN_SCOPE_SELECTION = [
    ('meter_product', 'Meter Product'),
    ('smt_pcb_board', 'SMT PCB Board'),
    ('pcba_module', 'PCBA Module'),
]


class LaserPrintRecord(models.Model):
    _name = 'sn.wsd.laser.print.record'
    _description = 'Laser Print Record'
    _order = 'print_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('sn.wsd.laser.print.record') or 'New',
        index=True,
    )
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    production_id = fields.Many2one('mrp.production', required=True, index=True, check_company=True)
    work_order_no = fields.Char(related='production_id.name', store=True, readonly=True, index=True)
    product_id = fields.Many2one(related='production_id.product_id', store=True, readonly=True, check_company=True)
    drawing_no = fields.Char(index=True)
    quantity = fields.Integer(required=True)
    operator_code = fields.Char(required=True, index=True)
    print_time = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    request_id = fields.Char(index=True)
    source_system = fields.Char(index=True)
    sn_scope = fields.Selection(
        LASER_SN_SCOPE_SELECTION,
        string='SN Scope',
        required=True,
        default='meter_product',
        index=True,
    )
    payload = fields.Json(copy=False)
    line_ids = fields.One2many('sn.wsd.laser.print.record.line', 'record_id', string='Printed Serials')

    _laser_request_company_unique = models.Constraint(
        'unique(company_id, request_id)',
        'The laser print request ID must be unique per company.',
    )

    @api.constrains('quantity')
    def _check_quantity(self):
        for record in self:
            if record.quantity <= 0:
                raise ValidationError(_('The print quantity must be positive.'))


class LaserPrintRecordLine(models.Model):
    _name = 'sn.wsd.laser.print.record.line'
    _description = 'Laser Print Record Line'
    _order = 'record_id, id'
    _check_company_auto = True

    record_id = fields.Many2one(
        'sn.wsd.laser.print.record',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(related='record_id.company_id', store=True, readonly=True)
    production_id = fields.Many2one(related='record_id.production_id', store=True, readonly=True, check_company=True)
    serial_no = fields.Char(required=True, index=True)
    lot_id = fields.Many2one('stock.lot', string='Inventory Lot', check_company=True, index=True)
    internal_serial_id = fields.Many2one('sn.wsd.internal.serial', check_company=True, index=True)
    pcb_board_id = fields.Many2one('sn.smt.pcb.board', string='SMT PCB Board', check_company=True, index=True)
    drawing_no = fields.Char(related='record_id.drawing_no', store=True, readonly=True)
    operator_code = fields.Char(related='record_id.operator_code', store=True, readonly=True)
    print_time = fields.Datetime(related='record_id.print_time', store=True, readonly=True)

    _laser_serial_company_unique = models.Constraint(
        'unique(company_id, serial_no)',
        'The laser printed serial number must be unique per company.',
    )

    @api.constrains('record_id', 'internal_serial_id', 'pcb_board_id')
    def _check_scope_target(self):
        for line in self:
            if line.record_id.sn_scope == 'meter_product' and not line.internal_serial_id:
                raise ValidationError(_('Meter product laser lines must be linked to a meter serial archive.'))

    def _ensure_internal_serials(self):
        serial_model = self.env['sn.wsd.internal.serial'].with_context(active_test=False)
        for line in self:
            if line.internal_serial_id or line.record_id.sn_scope != 'smt_pcb_board':
                continue
            production = line.production_id
            if not production:
                continue
            serial = serial_model.find_for_manufacturing_context(
                line.serial_no,
                company=line.company_id,
                production=production,
                mes_order=production.x_mes_order_ids[:1],
                product=production.product_id,
            )
            if not serial:
                serial = serial_model.create({
                    'serial_no': line.serial_no,
                    'barcode': line.serial_no,
                    'product_id': production.product_id.id,
                    'production_id': production.id,
                    'current_production_id': production.id,
                    'mes_order_id': production.x_mes_order_ids[:1].id,
                    'company_id': production.company_id.id,
                    'serial_type': 'semifinished',
                    'identity_origin_type': 'laser',
                })
            line.internal_serial_id = serial.id
        return self.mapped('internal_serial_id')


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_laser_drawing_no = fields.Char(string='Laser Drawing No')
    x_laser_print_record_ids = fields.One2many(
        'sn.wsd.laser.print.record',
        'production_id',
        string='Laser Print Records',
        readonly=True,
    )
    x_laser_print_record_count = fields.Integer(compute='_compute_laser_print_record_count')

    def _compute_laser_print_record_count(self):
        record_model = self.env['sn.wsd.laser.print.record']
        for production in self:
            production.x_laser_print_record_count = record_model.search_count([('production_id', '=', production.id)])

    def action_open_laser_print_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Laser Print Records'),
            'res_model': 'sn.wsd.laser.print.record',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id},
        }

    def _laser_serial_exists(self, serial_no, sn_scope=False):
        self.ensure_one()
        serial_exists = self.env['sn.wsd.internal.serial'].search_count([
            ('company_id', '=', self.company_id.id),
            ('serial_no', '=', serial_no),
        ], limit=1)
        laser_line_exists = self.env['sn.wsd.laser.print.record.line'].search_count([
            ('company_id', '=', self.company_id.id),
            ('serial_no', '=', serial_no),
        ], limit=1)
        if sn_scope == 'smt_pcb_board':
            return bool(serial_exists or laser_line_exists)
        return bool(
            self.env['stock.lot'].search_count([
                ('name', '=', serial_no),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            or serial_exists
            or laser_line_exists
        )

    def _get_laser_sn_scope(self, requested_scope=False):
        self.ensure_one()
        if requested_scope:
            valid_scopes = dict(LASER_SN_SCOPE_SELECTION)
            if requested_scope not in valid_scopes:
                raise ValidationError(_('Unsupported laser SN scope: %s') % requested_scope)
            return requested_scope
        if self.x_has_smt_operations:
            return 'smt_pcb_board'
        if self.x_has_meter_operations:
            return 'meter_product'
        raise ValidationError(_('Laser print is not supported for this manufacturing order type.'))

    def _next_laser_product_sn(self, sn_scope=False):
        self.ensure_one()
        for _index in range(100):
            serial_no = self.env['ir.sequence'].next_by_code('sn.wsd.laser.product.sn')
            if serial_no and not self._laser_serial_exists(serial_no, sn_scope=sn_scope):
                return serial_no
        raise ValidationError(_('Unable to generate a unique product serial number.'))

    def _validate_laser_print_quantity(self, quantity, sn_scope):
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            raise ValidationError(_('Manufacturing order is closed and cannot print serial numbers.'))
        if quantity <= 0:
            raise ValidationError(_('The print quantity must be positive.'))
        if sn_scope == 'pcba_module':
            raise ValidationError(_('PCBA module laser print is not implemented yet.'))
        if sn_scope == 'meter_product' and not self.x_has_meter_operations:
            raise ValidationError(_('Meter product serial numbers can only be printed for final assembly manufacturing orders.'))
        if sn_scope == 'smt_pcb_board' and not self.x_has_smt_operations:
            raise ValidationError(_('SMT PCB serial numbers can only be printed for SMT manufacturing orders.'))
        if sn_scope == 'smt_pcb_board':
            self._check_smt_laser_sn_capacity(quantity)
            return
        existing_count = len(self.x_internal_serial_ids)
        planned_qty = int(self.product_uom_id.round(self.product_qty))
        if existing_count + quantity > planned_qty:
            raise ValidationError(_('Print quantity cannot exceed the planned quantity.'))

    def _get_smt_laser_generated_sn_qty(self):
        self.ensure_one()
        return self.env['sn.wsd.laser.print.record.line'].search_count([
            ('production_id', '=', self.id),
            ('record_id.sn_scope', '=', 'smt_pcb_board'),
        ])

    def _check_smt_laser_sn_capacity(self, requested_qty):
        self.ensure_one()
        planned_qty = int(self.product_uom_id.round(self.product_qty))
        existing_qty = self._get_smt_laser_generated_sn_qty()
        available_qty = max(planned_qty - existing_qty, 0)
        if int(requested_qty or 0) > available_qty:
            raise ValidationError(_(
                'SMT laser SN quantity exceeds manufacturing order planned quantity. '
                'Planned: %(planned_qty)s, existing generated: %(existing_qty)s, requested: %(requested_qty)s, available: %(available_qty)s.'
            ) % {
                'planned_qty': planned_qty,
                'existing_qty': existing_qty,
                'requested_qty': int(requested_qty or 0),
                'available_qty': available_qty,
            })

    def _create_laser_lot(self, serial_no):
        self.ensure_one()
        identity = self.env['sn.wsd.serial.identity'].get_or_create(
            serial_no,
            self.company_id,
            origin_type='laser',
            origin_production_id=self,
        )
        return self.env['stock.lot'].create({
            'name': serial_no,
            'product_id': self.product_id.id,
            'company_id': self.company_id.id,
            'x_serial_identity_id': identity.id,
        })

    def _prepare_laser_record_values(self, quantity, drawing_no, operator_code, request_id, source_system, payload, sn_scope, line_commands):
        self.ensure_one()
        return {
            'company_id': self.company_id.id,
            'production_id': self.id,
            'drawing_no': drawing_no,
            'quantity': quantity,
            'operator_code': operator_code,
            'request_id': request_id,
            'source_system': source_system,
            'sn_scope': sn_scope,
            'payload': payload or {},
            'line_ids': line_commands,
        }

    def _api_request_meter_laser_print(self, quantity, drawing_no, operator_code, request_id, source_system, payload, sn_scope):
        self.ensure_one()
        mes_order = self.env['sn.wsd.mes.order'].browse(
            self.env.context.get('mes_order_id')
        ).exists() or self.x_mes_order_ids[:1]
        if not mes_order:
            raise ValidationError(_('Meter laser printing requires an MES order.'))
        archives = mes_order.action_generate_missing_internal_serials(quantity=quantity)
        line_commands = []
        serial_numbers = []
        for archive in archives:
            serial_numbers.append(archive.serial_no)
            line_commands.append(fields.Command.create({
                'serial_no': archive.serial_no,
                'internal_serial_id': archive.id,
            }))

        record = self.env['sn.wsd.laser.print.record'].create(
            self._prepare_laser_record_values(quantity, drawing_no, operator_code, request_id, source_system, payload, sn_scope, line_commands)
        )
        self._update_meter_flow_state()
        return {
            'record': record,
            'serial_numbers': serial_numbers,
            'archive_ids': archives.ids,
            'lot_ids': [],
            'pcb_board_ids': [],
            'pcb_panel_ids': [],
            'sn_scope': sn_scope,
        }

    def _api_request_smt_laser_print(self, quantity, drawing_no, operator_code, request_id, source_system, payload, sn_scope):
        self.ensure_one()
        mes_order = self.env['sn.wsd.mes.order'].browse(
            self.env.context.get('mes_order_id')
        ).exists() or self.x_mes_order_ids[:1]
        if not mes_order:
            raise ValidationError(_('SMT laser printing requires an MES order.'))
        archives = mes_order.action_generate_missing_internal_serials(quantity=quantity)
        line_commands = []
        serial_numbers = []
        for archive in archives:
            serial_numbers.append(archive.serial_no)
            line_commands.append(fields.Command.create({
                'serial_no': archive.serial_no,
                'internal_serial_id': archive.id,
            }))

        record = self.env['sn.wsd.laser.print.record'].create(
            self._prepare_laser_record_values(quantity, drawing_no, operator_code, request_id, source_system, payload, sn_scope, line_commands)
        )
        return {
            'record': record,
            'serial_numbers': serial_numbers,
            'archive_ids': archives.ids,
            'lot_ids': [],
            'pcb_board_ids': [],
            'pcb_panel_ids': [],
            'sn_scope': sn_scope,
        }

    def api_request_laser_print(
        self,
        quantity,
        drawing_no=False,
        operator_code=None,
        request_id=None,
        source_system='LASER',
        payload=None,
        sn_scope=False,
    ):
        self.ensure_one()
        quantity = int(quantity)
        sn_scope = self._get_laser_sn_scope(sn_scope)
        self._validate_laser_print_quantity(quantity, sn_scope)
        operator_code = operator_code or self.env.user.login or self.env.user.name
        if drawing_no:
            self.x_laser_drawing_no = drawing_no

        if sn_scope == 'smt_pcb_board':
            return self._api_request_smt_laser_print(quantity, drawing_no, operator_code, request_id, source_system, payload, sn_scope)
        return self._api_request_meter_laser_print(quantity, drawing_no, operator_code, request_id, source_system, payload, sn_scope)
