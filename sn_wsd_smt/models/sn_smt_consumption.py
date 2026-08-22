from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SnSmtOnlineMaterialExtension(models.Model):
    _inherit = 'sn.smt.online.material'

    required_product_id = fields.Many2one(
        'product.product',
        string='Main Material',
        compute='_compute_required_product_id',
        store=True,
        readonly=True,
        check_company=True,
    )
    required_item_code = fields.Char(
        string='Main Item Code',
        index=True,
    )

    @api.onchange('required_item_code')
    def _onchange_required_item_code(self):
        # 主料料号是手工录入入口，同步到 item_code 后由
        # _compute_required_product_id 反查产品带出名称/规格。
        if self.required_item_code:
            self.item_code = self.required_item_code

    @api.model_create_multi
    def create(self, vals_list):
        # item_code 不在视图中，onchange 的同步客户端不会回传，落库前强制对齐。
        for vals in vals_list:
            if vals.get('required_item_code') and not vals.get('item_code'):
                vals['item_code'] = vals['required_item_code']
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('required_item_code') and not vals.get('item_code'):
            vals['item_code'] = vals['required_item_code']
        return super().write(vals)
    required_product_name = fields.Char(
        string='Main Material Name',
        related='required_product_id.name',
        readonly=True,
    )
    required_product_spec = fields.Char(
        string='Main Material Specification',
        related='required_product_id.material_specification',
        store=True,
        readonly=True,
    )
    loaded_qty = fields.Float(string='Loaded Points', copy=False)
    consumed_qty = fields.Float(
        string='Consumed Points',
        compute='_compute_smt_quantities',
        store=True,
    )
    scrap_qty = fields.Float(string='Scrap Points', copy=False, default=0.0)
    remaining_qty = fields.Float(
        string='Remaining Points',
        compute='_compute_smt_quantities',
        store=True,
    )
    last_operation_type = fields.Selection(
        [
            ('offline_prepare', 'Offline Preparation'),
            ('online_load', 'Load'),
            ('unload', 'Unload'),
            ('change', 'Change'),
            ('continue', 'Continue'),
            ('changeover_inherit', 'Changeover Inherit'),
        ],
        string='Last Operation',
        copy=False,
    )
    last_consumed_serial_id = fields.Many2one(
        'sn.wsd.internal.serial', string='Last Product SN', copy=False, check_company=True,
    )
    last_consumed_at = fields.Datetime(string='Last Consumption Time', copy=False)
    loaded_at = fields.Datetime(string='Loaded At', copy=False)
    consumption_ids = fields.One2many(
        'sn.smt.material.consumption', 'online_material_id', string='SN Consumption',
    )

    @api.depends('item_code')
    def _compute_required_product_id(self):
        product_model = self.env['product.product']
        for line in self:
            if line.item_code:
                line.required_product_id = product_model.search(
                    [('default_code', '=', line.item_code)], limit=1,
                )
            else:
                line.required_product_id = False

    @api.depends('consumption_ids.consumed_qty', 'loaded_qty', 'scrap_qty')
    def _compute_smt_quantities(self):
        for line in self:
            consumed = sum(line.consumption_ids.mapped('consumed_qty'))
            line.consumed_qty = consumed
            line.remaining_qty = max(line.loaded_qty - consumed - line.scrap_qty, 0.0)

    def _set_loaded_quantity(self, material_lot):
        self.ensure_one()
        available_qty = material_lot.x_smt_available_qty or material_lot.product_qty
        values = {
            'loaded_qty': available_qty,
            'loaded_at': fields.Datetime.now(),
            'last_operation_type': 'online_load',
        }
        self.write(values)


class SnSmtTraceabilityExtension(models.Model):
    _inherit = 'sn.smt.traceability'

    required_item_code = fields.Char(
        string='Main Item Code', related='online_material_id.required_item_code', store=True, readonly=True,
    )
    actual_item_code = fields.Char(
        string='Actual Item Code', related='material_lot_id.product_id.default_code', store=True, readonly=True,
    )


class SnSmtMaterialConsumption(models.Model):
    _name = 'sn.smt.material.consumption'
    _description = 'SMT Material Consumption by Product Serial'
    _order = 'consumed_at desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial', string='Product SN', required=True,
        ondelete='restrict', index=True, check_company=True,
    )
    serial_no = fields.Char(related='internal_serial_id.serial_no', store=True, readonly=True, index=True)
    production_id = fields.Many2one('mrp.production', required=True, index=True, check_company=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', related='production_id.x_mes_order_id',
        store=True, readonly=True, index=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        required=True,
        index=True,
        check_company=True,
    )
    online_material_id = fields.Many2one(
        'sn.smt.online.material', required=True, ondelete='restrict', index=True, check_company=True,
    )
    material_lot_id = fields.Many2one(
        'stock.lot', string='Material SN', required=True, ondelete='restrict', index=True, check_company=True,
    )
    material_sn = fields.Char(related='material_lot_id.name', store=True, readonly=True, index=True)
    required_product_id = fields.Many2one(
        'product.product', related='online_material_id.required_product_id', store=True, readonly=True,
    )
    required_item_code = fields.Char(related='online_material_id.required_item_code', store=True, readonly=True)
    actual_product_id = fields.Many2one(
        'product.product', related='material_lot_id.product_id', store=True, readonly=True,
    )
    actual_item_code = fields.Char(related='actual_product_id.default_code', store=True, readonly=True)
    device_seq = fields.Integer(related='online_material_id.device_seq', store=True, readonly=True)
    table_no = fields.Char(related='online_material_id.table_no', store=True, readonly=True)
    loadpoint = fields.Char(related='online_material_id.loadpoint', store=True, readonly=True)
    chanel_sn = fields.Char(related='online_material_id.chanel_sn', store=True, readonly=True)
    process_face = fields.Selection(related='online_material_id.process_face', store=True, readonly=True)
    feeder_id = fields.Many2one('sn.smt.feeder', check_company=True)
    point_qty = fields.Float(string='Point Qty', required=True)
    product_qty = fields.Float(string='Product Qty', default=1.0, required=True)
    consumed_qty = fields.Float(string='Consumed Points', required=True)
    qty_before = fields.Float(string='Points Before', required=True)
    qty_after = fields.Float(string='Points After', required=True)
    consumed_at = fields.Datetime(string='Consumed At', required=True, default=fields.Datetime.now, index=True)
    operator_code = fields.Char(string='Operator Code', index=True)
    external_event_id = fields.Char(string='External Event ID', index=True, copy=False)
    source_system = fields.Char(string='Source System', index=True)
    reversed_id = fields.Many2one('sn.smt.material.consumption', string='Reversal', copy=False, check_company=True)
    note = fields.Char(string='Note')

    _smt_consumption_event_unique = models.Constraint(
        'unique(internal_serial_id, route_operation_id, online_material_id, external_event_id)',
        'A product serial can only consume one material position per event.',
    )

    @api.model
    def _get_active_lines(self, route_operation):
        return route_operation.mes_order_id.production_id.x_smt_online_material_ids.filtered(
            lambda line: line.is_skip != 'Y' and line.is_load == 'Y' and line.loaded_material_lot_id
        )

    @api.model
    def validate_for_serial(self, route_operation, internal_serial):
        if not route_operation or route_operation.operation_id.x_station_type not in ('smt', 'dip'):
            return self.env['sn.smt.online.material']
        production = route_operation.mes_order_id.production_id
        lines = self._get_active_lines(route_operation)
        expected_lines = production.x_smt_online_material_ids.filtered(lambda line: line.is_skip != 'Y')
        if len(lines) != len(expected_lines):
            raise ValidationError(_('All SMT material positions must be loaded before the product can pass this station.'))
        if not lines:
            raise ValidationError(_('No active SMT material positions are available for this route operation.'))
        self.env.cr.execute(
            'SELECT id FROM sn_smt_online_material WHERE id IN %s FOR UPDATE', [tuple(lines.ids)],
        )
        lines.invalidate_recordset(['consumed_qty', 'remaining_qty'])
        shortages = lines.filtered(lambda line: line.remaining_qty < (line.point_qty or 1.0))
        if shortages:
            shortage = shortages[0]
            raise ValidationError(_(
                'SMT material %(material)s at loadpoint %(loadpoint)s has insufficient points.',
                material=shortage.loaded_material_lot_id.name,
                loadpoint=shortage.loadpoint,
            ))
        return lines

    @api.model
    def consume_for_serial(self, route_operation, internal_serial, operator_code=None,
                           external_event_id=None, source_system=None, note=None):
        lines = self.validate_for_serial(route_operation, internal_serial)
        if not lines:
            return self.env['sn.smt.material.consumption']
        existing_domain = [
            ('internal_serial_id', '=', internal_serial.id),
            ('route_operation_id', '=', route_operation.id),
        ]
        if external_event_id:
            existing_domain.append(('external_event_id', '=', external_event_id))
            existing = self.search(existing_domain)
            if existing:
                return existing
        created = self.env['sn.smt.material.consumption']
        for line in lines:
            point_qty = line.point_qty or 1.0
            before = line.remaining_qty
            after = before - point_qty
            record = self.create({
                'company_id': route_operation.company_id.id,
                'internal_serial_id': internal_serial.id,
                'production_id': route_operation.mes_order_id.production_id.id,
                'route_operation_id': route_operation.id,
                'online_material_id': line.id,
                'material_lot_id': line.loaded_material_lot_id.id,
                'feeder_id': line.loaded_feeder_id.id,
                'point_qty': point_qty,
                'product_qty': 1.0,
                'consumed_qty': point_qty,
                'qty_before': before,
                'qty_after': max(after, 0.0),
                'operator_code': operator_code,
                'external_event_id': external_event_id,
                'source_system': source_system,
                'note': note,
            })
            created |= record
            line.write({
                'last_consumed_serial_id': internal_serial.id,
                'last_consumed_at': record.consumed_at,
            })
        return created

    def action_reverse(self, note=None):
        self.ensure_one()
        if self.reversed_id:
            raise ValidationError(_('This SMT consumption has already been reversed.'))
        reversal = self.create({
            'company_id': self.company_id.id,
            'internal_serial_id': self.internal_serial_id.id,
            'production_id': self.production_id.id,
            'route_operation_id': self.route_operation_id.id,
            'online_material_id': self.online_material_id.id,
            'material_lot_id': self.material_lot_id.id,
            'feeder_id': self.feeder_id.id,
            'point_qty': self.point_qty,
            'product_qty': -1.0,
            'consumed_qty': -self.consumed_qty,
            'qty_before': self.qty_after,
            'qty_after': self.qty_before,
            'operator_code': self.env.user.login,
            'source_system': 'reversal',
            'note': note or _('Reversal of SMT material consumption.'),
        })
        self.reversed_id = reversal.id
        return reversal


class InternalSerialSmtExtension(models.Model):
    _inherit = 'sn.wsd.internal.serial'

    smt_consumption_ids = fields.One2many(
        'sn.smt.material.consumption', 'internal_serial_id', string='SMT Material Consumption',
    )
    smt_consumption_count = fields.Integer(
        string='SMT Consumption Count', compute='_compute_smt_consumption_count',
    )

    @api.depends('smt_consumption_ids')
    def _compute_smt_consumption_count(self):
        for serial in self:
            serial.smt_consumption_count = len(serial.smt_consumption_ids)

    def action_view_smt_consumption(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SMT Material Consumption'),
            'res_model': 'sn.smt.material.consumption',
            'view_mode': 'list,form',
            'domain': [('internal_serial_id', '=', self.id)],
            'context': {'default_internal_serial_id': self.id},
        }


class SnSmtLoadingService(models.AbstractModel):
    _name = 'sn.smt.loading.service'
    _description = 'SMT PDA Loading Service'

    @api.model
    def _new_loading_wizard(self, production, workcenter, device_table, loadpoint, feeder_sn, material_sn):
        return self.env['sn.smt.tp.wizard'].new({
            'company_id': production.company_id.id,
            'production_id': production.id,
            'workcenter_id': workcenter.id,
            'device_table_input': device_table,
            'loadpoint_input': loadpoint,
            'feeder_input': feeder_sn,
            'material_sn_input': material_sn,
        })

    @api.model
    def validate_loading(self, production, workcenter, device_table, loadpoint, feeder_sn, material_sn):
        wizard = self._new_loading_wizard(
            production, workcenter, device_table, loadpoint, feeder_sn, material_sn,
        )
        wizard.action_validate()
        return {
            'online_material_id': wizard.online_material_id.id,
            'material_lot_id': wizard.material_lot_id.id,
            'feeder_id': wizard.feeder_id.id,
            'message': wizard.message,
        }


class StockLotSmtConsumptionExtension(models.Model):
    _inherit = 'stock.lot'

    smt_consumption_ids = fields.One2many(
        'sn.smt.material.consumption', 'material_lot_id', string='SMT Product Usage',
    )
    smt_consumption_count = fields.Integer(
        string='SMT Product Usage Count', compute='_compute_smt_consumption_count',
    )

    @api.depends('smt_consumption_ids')
    def _compute_smt_consumption_count(self):
        for lot in self:
            lot.smt_consumption_count = len(lot.smt_consumption_ids)

    def action_view_smt_consumption(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SMT Product Usage'),
            'res_model': 'sn.smt.material.consumption',
            'view_mode': 'list,form',
            'domain': [('material_lot_id', '=', self.id)],
            'context': {'default_material_lot_id': self.id},
        }

    @api.model
    def save_loading(self, production, workcenter, device_table, loadpoint, feeder_sn, material_sn):
        wizard = self._new_loading_wizard(
            production, workcenter, device_table, loadpoint, feeder_sn, material_sn,
        )
        wizard.action_save()
        return {
            'online_material_id': wizard.online_material_id.id,
            'material_lot_id': wizard.material_lot_id.id,
            'feeder_id': wizard.feeder_id.id,
            'message': wizard.message,
        }
