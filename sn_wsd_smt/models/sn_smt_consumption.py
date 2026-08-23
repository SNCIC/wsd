from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .sn_smt_material_table import MATERIAL_LOG_OPERATION_SELECTION


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
        tracking=False,
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
        store=True,
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
    remaining_qty = fields.Float(
        string='Remaining Points',
        compute='_compute_smt_quantities',
        store=True,
    )
    last_operation_type = fields.Selection(
        MATERIAL_LOG_OPERATION_SELECTION,
        string='Last Operation',
        copy=False,
    )
    last_consumed_serial_id = fields.Many2one(
        'sn.wsd.serial.identity', string='Last Product SN', copy=False, check_company=True,
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

    @api.depends('consumption_ids.consumed_qty', 'loaded_qty')
    def _compute_smt_quantities(self):
        for line in self:
            consumed = sum(line.consumption_ids.mapped('consumed_qty'))
            line.consumed_qty = consumed
            line.remaining_qty = max(line.loaded_qty - consumed, 0.0)

    def _set_loaded_quantity(self, material_lot, operation_type='online_load'):
        """上料时取卷的点数账本余额作为本次上机的初始数量——
        同一卷跨制令单再次上机时，余量自动延续。最近操作随调用方
        （上料/换料/续料/转机继承）写入。"""
        self.ensure_one()
        values = {
            'loaded_qty': material_lot.x_smt_point_balance,
            'loaded_at': fields.Datetime.now(),
            'last_operation_type': operation_type,
        }
        self.write(values)


class SnSmtMaterialConsumption(models.Model):
    _name = 'sn.smt.material.consumption'
    _description = 'SMT Material Consumption by Product Serial'
    _order = 'consumed_at desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True,
    )
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN', required=True,
        ondelete='restrict', index=True, check_company=True,
    )
    serial_no = fields.Char(related='serial_identity_id.name', store=True, readonly=True, index=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True, index=True, check_company=True,
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
        'unique(serial_identity_id, route_operation_id, online_material_id, external_event_id)',
        'A product serial can only consume one material position per event.',
    )

    @api.model
    def _get_active_lines(self, route_operation):
        return route_operation.mes_order_id.x_smt_online_material_ids.filtered(
            lambda line: line.is_skip != 'Y' and line.is_load == 'Y' and line.loaded_material_lot_id
        )

    @api.model
    def validate_for_serial(self, route_operation, identity=False):
        # 触发条件：制令单路线工艺类型为 SMT，且已拆出在线料表行。
        mes_order = route_operation.mes_order_id
        if not mes_order.x_smt_online_material_ids:
            return self.env['sn.smt.online.material']
        if not mes_order._is_smt_route_order():
            return self.env['sn.smt.online.material']
        lines = self._get_active_lines(route_operation)
        expected_lines = mes_order.x_smt_online_material_ids.filtered(lambda line: line.is_skip != 'Y')
        if len(lines) != len(expected_lines):
            raise ValidationError(_('All SMT material positions must be loaded before the product can pass this station.'))
        if not lines:
            return self.env['sn.smt.online.material']
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
    def consume_for_serial(self, route_operation, identity=False, operator_code=None,
                           external_event_id=None, source_system=None, note=None):
        lines = self.validate_for_serial(route_operation, identity)
        if not lines:
            return self.env['sn.smt.material.consumption']
        mes_order = route_operation.mes_order_id
        # 一块板一张料站表只扣一次：同 SN 在本制令单已有正向扣点流水则跳过
        # （SMT 车间路线含多道工序，板会在多站过站，按单幂等防止重复扣点）。
        existing_domain = [
            ('serial_identity_id', '=', identity.id),
            ('mes_order_id', '=', mes_order.id),
            ('product_qty', '>', 0),
        ]
        existing = self.search(existing_domain, limit=1)
        if existing:
            return existing
        if external_event_id:
            existing = self.search([
                ('serial_identity_id', '=', identity.id),
                ('route_operation_id', '=', route_operation.id),
                ('external_event_id', '=', external_event_id),
            ])
            if existing:
                return existing
        created = self.env['sn.smt.material.consumption']
        for line in lines:
            point_qty = line.point_qty or 1.0
            before = line.remaining_qty
            after = before - point_qty
            record = self.create({
                'company_id': route_operation.company_id.id,
                'serial_identity_id': identity.id,
                'mes_order_id': mes_order.id,
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
                'last_consumed_serial_id': identity.id,
                'last_consumed_at': record.consumed_at,
            })
        return created

    def action_reverse(self, note=None):
        self.ensure_one()
        if self.reversed_id:
            raise ValidationError(_('This SMT consumption has already been reversed.'))
        reversal = self.create({
            'company_id': self.company_id.id,
            'serial_identity_id': self.serial_identity_id.id,
            'mes_order_id': self.mes_order_id.id,
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


class SerialIdentitySmtExtension(models.Model):
    _inherit = 'sn.wsd.serial.identity'

    smt_consumption_ids = fields.One2many(
        'sn.smt.material.consumption', 'serial_identity_id', string='SMT Material Consumption',
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
            'name': 'Product Material Usage',
            'res_model': 'sn.smt.material.consumption',
            'view_mode': 'list,form',
            'domain': [('serial_identity_id', '=', self.id)],
            'context': {'default_serial_identity_id': self.id},
        }
