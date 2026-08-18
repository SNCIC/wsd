from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


COMPONENT_TYPE_SELECTION = [
    ('main_pcb', 'Main PCB'),
    ('comm_module', 'Communication Module'),
    ('display_module', 'Display Module'),
    ('mcu', 'MCU'),
    ('metering_chip', 'Metering Chip'),
    ('relay', 'Relay'),
    ('ct', 'Current Transformer'),
    ('shunt', 'Shunt'),
    ('esam', 'ESAM'),
    ('sim', 'SIM'),
    ('security_chip', 'Security Chip'),
    ('other', 'Other'),
]


class MeterComponentBinding(models.Model):
    _name = 'sn.wsd.meter.component.binding'
    _description = 'Meter Component Binding Event'
    _order = 'event_time desc, id desc'
    _rec_name = 'display_name'
    _check_company_auto = True

    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Meter Serial',
        required=True,
        index=True,
        ondelete='cascade',
        check_company=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='internal_serial_id.production_id',
        store=True,
        readonly=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='internal_serial_id.mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Route Operation',
        check_company=True,
        index=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='MES Work Center',
        check_company=True,
        index=True,
    )
    component_type = fields.Selection(
        COMPONENT_TYPE_SELECTION,
        string='Component Type',
        required=True,
        index=True,
    )
    event_type = fields.Selection(
        [
            ('bind', 'Bind'),
            ('replace', 'Replace'),
            ('unbind', 'Unbind'),
            ('verify', 'Verify'),
        ],
        string='Event Type',
        required=True,
        default='bind',
        index=True,
    )
    state = fields.Selection(
        [
            ('active', 'Active'),
            ('replaced', 'Replaced'),
            ('removed', 'Removed'),
        ],
        string='Binding State',
        required=True,
        default='active',
        index=True,
    )
    event_time = fields.Datetime(
        string='Event Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    operator_code = fields.Char(string='Operator Code', index=True)
    component_product_id = fields.Many2one(
        'product.product',
        string='Component Product',
        check_company=True,
        index=True,
    )
    component_lot_id = fields.Many2one(
        'stock.lot',
        string='Component Lot/Serial',
        check_company=True,
        index=True,
    )
    component_sn = fields.Char(string='Component SN', index=True)
    component_batch_no = fields.Char(string='Component Batch No.', index=True)
    vendor_batch_no = fields.Char(string='Vendor Batch No.')
    imei = fields.Char(string='IMEI', index=True)
    iccid = fields.Char(string='ICCID', index=True)
    imsi = fields.Char(string='IMSI', index=True)
    esam_no = fields.Char(string='ESAM No.', index=True)
    security_chip_no = fields.Char(string='Security Chip No.', index=True)
    note = fields.Char(string='Note')
    payload = fields.Json(string='Payload')

    @api.depends('internal_serial_id.serial_no', 'component_type', 'component_sn', 'component_batch_no')
    def _compute_display_name(self):
        for record in self:
            component_identity = record.component_sn or record.component_batch_no or '-'
            record.display_name = ' / '.join(
                item
                for item in [
                    record.internal_serial_id.serial_no or '-',
                    dict(COMPONENT_TYPE_SELECTION).get(record.component_type, record.component_type or '-'),
                    component_identity,
                ]
                if item
            )

    @api.constrains('component_product_id', 'component_lot_id')
    def _check_component_lot_product(self):
        for record in self:
            if (
                record.component_product_id
                and record.component_lot_id
                and record.component_lot_id.product_id != record.component_product_id
            ):
                raise ValidationError(_('The component lot/serial must belong to the selected component product.'))

    @api.model
    def _component_field_map(self):
        return {
            'main_pcb': 'main_pcb_sn',
            'comm_module': 'comm_module_sn',
            'display_module': 'display_module_sn',
        }

    @api.model
    def _prepare_component_binding_vals(self, internal_serial, component_data, workorder=False, test_result=False):
        component_product = self.env['product.product']
        component_lot = self.env['stock.lot']
        product_id = component_data.get('component_product_id')
        lot_id = component_data.get('component_lot_id')
        component_sn = component_data.get('component_sn')

        if product_id:
            component_product = self.env['product.product'].browse(product_id).exists()
        if lot_id:
            component_lot = self.env['stock.lot'].browse(lot_id).exists()
        elif component_sn and component_product:
            component_lot = self.env['stock.lot'].search([
                ('name', '=', component_sn),
                ('product_id', '=', component_product.id),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', internal_serial.company_id.id),
            ], limit=1)

        station = self.env['mrp.workcenter']
        if workorder and workorder.x_mes_workcenter_id:
            station = workorder.x_mes_workcenter_id
        elif test_result and test_result.workcenter_id:
            station = test_result.workcenter_id

        return {
            'company_id': internal_serial.company_id.id,
            'internal_serial_id': internal_serial.id,
            'route_operation_id': workorder.id if workorder else False,
            'workcenter_id': station.id if station else False,
            'component_type': component_data['component_type'],
            'event_type': component_data.get('event_type', 'bind'),
            'state': component_data.get('state', 'active'),
            'event_time': component_data.get('event_time') or fields.Datetime.now(),
            'operator_code': component_data.get('operator_code') or (test_result.operator_code if test_result else False),
            'component_product_id': component_product.id if component_product else False,
            'component_lot_id': component_lot.id if component_lot else False,
            'component_sn': component_sn or (component_lot.name if component_lot else False),
            'component_batch_no': component_data.get('component_batch_no'),
            'vendor_batch_no': component_data.get('vendor_batch_no'),
            'imei': component_data.get('imei'),
            'iccid': component_data.get('iccid'),
            'imsi': component_data.get('imsi'),
            'esam_no': component_data.get('esam_no'),
            'security_chip_no': component_data.get('security_chip_no'),
            'note': component_data.get('note'),
            'payload': component_data.get('payload') or {},
        }

    @api.model
    def register_component_bindings(self, internal_serial, component_bindings, workorder=False, test_result=False):
        if not internal_serial or not component_bindings:
            return self.env['sn.wsd.meter.component.binding']

        active_bindings = self.search([
            ('internal_serial_id', '=', internal_serial.id),
            ('state', '=', 'active'),
        ])
        created_bindings = self.env['sn.wsd.meter.component.binding']
        field_map = self._component_field_map()
        legacy_updates = {}

        for component_data in component_bindings:
            component_type = component_data.get('component_type')
            if not component_type:
                continue
            active_same_type = active_bindings.filtered(lambda item: item.component_type == component_type)
            if active_same_type and component_data.get('event_type', 'bind') in ('bind', 'replace'):
                active_same_type.write({'state': 'replaced'})
            vals = self._prepare_component_binding_vals(
                internal_serial,
                component_data,
                workorder=workorder,
                test_result=test_result,
            )
            created_binding = self.create(vals)
            created_bindings |= created_binding
            active_bindings |= created_binding
            if component_type in field_map and created_binding.component_sn:
                legacy_updates[field_map[component_type]] = created_binding.component_sn

        if legacy_updates:
            internal_serial.write(legacy_updates)
        return created_bindings


class InternalSerial(models.Model):
    _inherit = 'sn.wsd.internal.serial'

    component_binding_ids = fields.One2many(
        'sn.wsd.meter.component.binding',
        'internal_serial_id',
        string='Component Binding History',
    )
    active_component_binding_ids = fields.Many2many(
        'sn.wsd.meter.component.binding',
        compute='_compute_component_binding_summary',
        string='Active Component Bindings',
    )
    component_binding_count = fields.Integer(
        string='Component Binding Count',
        compute='_compute_component_binding_summary',
    )
    active_component_binding_count = fields.Integer(
        string='Active Component Binding Count',
        compute='_compute_component_binding_summary',
    )

    def _compute_component_binding_summary(self):
        for record in self:
            active_bindings = record.component_binding_ids.filtered(lambda item: item.state == 'active')
            record.active_component_binding_ids = active_bindings
            record.component_binding_count = len(record.component_binding_ids)
            record.active_component_binding_count = len(active_bindings)

    def action_view_component_bindings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Component Bindings'),
            'res_model': 'sn.wsd.meter.component.binding',
            'view_mode': 'list,form',
            'domain': [('internal_serial_id', '=', self.id)],
            'context': {
                'default_internal_serial_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }


class MesTestResult(models.Model):
    _inherit = 'sn.wsd.mes.test.result'

    component_binding_ids = fields.One2many(
        'sn.wsd.meter.component.binding',
        compute='_compute_component_binding_ids',
        string='Component Bindings',
    )
    component_binding_count = fields.Integer(
        string='Component Binding Count',
        compute='_compute_component_binding_ids',
    )

    def _compute_component_binding_ids(self):
        binding_model = self.env['sn.wsd.meter.component.binding']
        for record in self:
            bindings = binding_model
            if record.internal_serial_id and record.route_operation_id:
                bindings = record.internal_serial_id.component_binding_ids.filtered(
                    lambda item: item.route_operation_id == record.route_operation_id
                )
            record.component_binding_ids = bindings
            record.component_binding_count = len(bindings)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        binding_model = self.env['sn.wsd.meter.component.binding']
        for record, vals in zip(records, vals_list):
            payload = vals.get('payload') or record.payload or {}
            component_bindings = payload.get('component_bindings') or []
            if not component_bindings or not record.internal_serial_id:
                continue
            binding_model.register_component_bindings(
                record.internal_serial_id,
                component_bindings,
                workorder=record.route_operation_id,
                test_result=record,
            )
        return records


class StockLot(models.Model):
    _inherit = 'stock.lot'

    x_meter_component_binding_ids = fields.One2many(
        'sn.wsd.meter.component.binding',
        'component_lot_id',
        string='Meter Component Bindings',
    )

