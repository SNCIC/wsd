from odoo import api, Command, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class ProductProduct(models.Model):
    _inherit = 'product.product'

    substitute_ids = fields.Many2many(
        'product.product',
        'product_substitute_rel',
        'product_id',
        'substitute_id',
        string='Substitute Products',
        help='Equivalent products allowed as substitutes when this item is short.',
    )
    substitute_for_ids = fields.Many2many(
        'product.product',
        'product_substitute_rel',
        'substitute_id',
        'product_id',
        string='Substitute For',
        help='Products that can be replaced by this item.',
    )


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    substitute_line_ids = fields.One2many(
        'mrp.bom.line.substitute',
        'bom_id',
        string='Substitute Materials',
    )

    def _find_bom_line_by_product(self, product):
        self.ensure_one()
        return self.bom_line_ids.filtered(lambda line: line.product_id == product)[:1]

    def _get_substitute_bom_line(self, original_product, substitute_product):
        self.ensure_one()
        bom_line = self._find_bom_line_by_product(original_product)
        if not bom_line:
            return self.env['mrp.bom.line']
        return bom_line.filtered(
            lambda line: substitute_product in line.substitute_line_ids.substitute_product_id
        )[:1]


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    x_requires_feeder_verification = fields.Boolean(
        string='Requires Feeder Verification',
        default=False,
        help='Legacy non-SMT feeder verification flag. SMT feeder verification is driven by SMT material tables.',
    )
    substitute_line_ids = fields.One2many(
        'mrp.bom.line.substitute',
        'bom_line_id',
        string='Substitute Materials',
        copy=True,
    )
    substitute_rule_count = fields.Integer(
        string='Substitute Rule Count',
        compute='_compute_substitute_rule_count',
    )

    @api.depends('substitute_line_ids')
    def _compute_substitute_rule_count(self):
        for line in self:
            line.substitute_rule_count = len(line.substitute_line_ids)

    def _get_allowed_substitute_lines(self):
        self.ensure_one()
        return self.substitute_line_ids.sorted(key=lambda item: (item.priority, item.id))


class MrpBomLineSubstitute(models.Model):
    _name = 'mrp.bom.line.substitute'
    _description = 'BoM Line Substitute Material'
    _order = 'priority, id'
    _check_company_auto = True

    bom_line_id = fields.Many2one(
        'mrp.bom.line',
        string='BoM Line',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    bom_id = fields.Many2one(
        'mrp.bom',
        string='BoM',
        related='bom_line_id.bom_id',
        store=True,
        index=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='bom_line_id.company_id',
        store=True,
        readonly=True,
    )
    original_product_id = fields.Many2one(
        'product.product',
        string='Original Product',
        related='bom_line_id.product_id',
        store=True,
        readonly=True,
    )
    substitute_product_id = fields.Many2one(
        'product.product',
        string='Substitute Product',
        required=True,
        check_company=True,
        domain="[('id', '!=', original_product_id)]",
    )
    priority = fields.Integer(
        string='Priority',
        default=10,
        required=True,
        help='Smaller values have higher priority.',
    )

    _unique_bom_line_substitute = models.Constraint(
        'unique(bom_line_id, substitute_product_id)',
        'The same substitute product can only be configured once for a BoM line.',
    )

    @api.constrains('bom_line_id', 'substitute_product_id')
    def _check_substitute_product_id(self):
        for record in self:
            if record.substitute_product_id == record.original_product_id:
                raise ValidationError(_('The substitute product must be different from the original product.'))


class StockMove(models.Model):
    _inherit = 'stock.move'

    excess_return_id = fields.Many2one(
        'mrp.excess.return',
        string='Excess Return',
        copy=False,
        index=True,
        check_company=True,
    )


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    can_return_excess = fields.Boolean(
        string='Can Return Excess',
        compute='_compute_can_return_excess',
        help='Whether finished raw moves contain excess material that can be returned.',
    )
    excess_return_ids = fields.One2many(
        'mrp.excess.return',
        'production_id',
        string='Excess Returns',
    )
    excess_return_count = fields.Integer(
        string='Excess Return Count',
        compute='_compute_excess_return_count',
    )
    substitute_usage_ids = fields.One2many(
        'mrp.substitute.usage',
        'production_id',
        string='Substitute Usage',
    )
    feeder_line_ids = fields.One2many(
        'mrp.feeder.line',
        'production_id',
        string='Feeder Lines',
    )

    def _requires_feeder_verification(self):
        self.ensure_one()
        feeder_operations = self.x_mes_order_id.x_route_operation_ids.filtered(
            lambda operation: operation.operation_id.x_station_type in ('smt', 'dip')
        )
        return bool(feeder_operations)

    @api.depends('move_raw_ids.state', 'move_raw_ids.product_uom_qty', 'move_raw_ids.quantity')
    def _compute_can_return_excess(self):
        for production in self:
            production.can_return_excess = bool(production._get_excess_raw_moves())

    @api.depends('excess_return_ids')
    def _compute_excess_return_count(self):
        for production in self:
            production.excess_return_count = len(production.excess_return_ids)

    def _get_excess_raw_moves(self):
        self.ensure_one()
        return self.move_raw_ids.filtered(
            lambda move: move.state == 'done'
            and float_compare(
                move.product_uom_qty,
                move.quantity,
                precision_rounding=move.product_uom.rounding,
            ) > 0
            and float_compare(
                move.quantity,
                0.0,
                precision_rounding=move.product_uom.rounding,
            ) > 0
        )

    def _find_bom_line_by_product(self, product):
        self.ensure_one()
        return self.bom_id._find_bom_line_by_product(product) if self.bom_id else self.env['mrp.bom.line']

    def _is_allowed_substitute_product(self, original_product, candidate_product):
        self.ensure_one()
        if not original_product or not candidate_product:
            return False
        if candidate_product == original_product:
            return True
        if self.bom_id:
            bom_line = self._find_bom_line_by_product(original_product)
            if bom_line and candidate_product in bom_line.substitute_line_ids.substitute_product_id:
                return True
        return candidate_product in original_product.substitute_ids or original_product in candidate_product.substitute_for_ids

    def _find_matching_raw_moves(self, material_product):
        self.ensure_one()
        return self.move_raw_ids.filtered(
            lambda move: move.state != 'cancel' and self._is_allowed_substitute_product(move.product_id, material_product)
        )

    def _generate_feeder_lines(self):
        self.ensure_one()
        if not self._requires_feeder_verification():
            return
        existing_lines = self.feeder_line_ids.filtered(lambda line: line.state != 'returned')
        if existing_lines:
            return

        commands = []
        raw_moves = self.move_raw_ids.filtered(
            lambda move: move.bom_line_id
            and move.bom_line_id.x_requires_feeder_verification
            and move.state != 'cancel'
        )
        feeder_operations = self.x_mes_order_id.x_route_operation_ids.filtered(
            lambda operation: operation.operation_id.x_station_type in ('smt', 'dip')
        )
        bom_feeder_operations = feeder_operations.filtered(
            lambda operation: operation.operation_id.x_station_type != 'smt'
        )
        if not bom_feeder_operations:
            return
        for feeder_index, move in enumerate(raw_moves, start=1):
            route_operation = bom_feeder_operations[:1]
            if not route_operation:
                continue
            commands.append(Command.create({
                'route_operation_id': route_operation.id,
                'production_id': self.id,
                'feeder_no': f'F{feeder_index:02d}',
                'expected_product_id': move.product_id.id,
                'source_move_id': move.id,
                'expected_qty': move.product_uom_qty,
                'state': 'pending',
            }))
        if commands:
            self.write({'feeder_line_ids': commands})

    def _sync_feeder_consumption(self):
        for production in self:
            feeder_lines = production.feeder_line_ids.filtered(
                lambda line: line.state in ('verified', 'consuming', 'depleted', 'returned')
            )
            for line in feeder_lines:
                if line.source_move_id:
                    if not line.source_move_id.picked:
                        continue
                    line.consumed_qty = line.source_move_id.quantity
                    if line.state == 'verified' and float_compare(
                        line.consumed_qty,
                        0.0,
                        precision_rounding=line.uom_id.rounding or 0.01,
                    ) > 0:
                        line.state = 'consuming'

    def _finalize_feeder_lines(self):
        for production in self:
            for line in production.feeder_line_ids.filtered(
                lambda item: item.state in ('verified', 'consuming')
            ):
                vals = {'unload_datetime': fields.Datetime.now()}
                vals['state'] = 'returned' if float_compare(
                    line.remaining_qty,
                    0.0,
                    precision_rounding=line.uom_id.rounding or 0.01,
                ) > 0 else 'depleted'
                line.write(vals)

    def action_confirm(self):
        res = super().action_confirm()
        for production in self:
            production._generate_feeder_lines()
        return res

    def _post_inventory(self, cancel_backorder=False):
        res = super()._post_inventory(cancel_backorder=cancel_backorder)
        for production in self:
            production._sync_feeder_consumption()
            production._finalize_feeder_lines()
        return res

    def action_create_excess_return(self):
        self.ensure_one()
        excess_moves = self._get_excess_raw_moves()
        if not excess_moves:
            raise UserError(_('No excess material is available for return.'))

        return_order = self.env['mrp.excess.return'].create({
            'production_id': self.id,
        })
        line_commands = []
        for move in excess_moves:
            remaining_qty = move.product_uom_qty - move.quantity
            move_lines = move.move_line_ids.filtered(
                lambda line: float_compare(
                    line.quantity,
                    0.0,
                    precision_rounding=line.product_uom_id.rounding,
                ) > 0
            )
            for move_line in move_lines:
                line_qty = move_line.product_uom_id._compute_quantity(
                    move_line.quantity,
                    move.product_uom,
                    rounding_method='HALF-UP',
                )
                qty_to_return = min(remaining_qty, line_qty)
                if float_compare(
                    qty_to_return,
                    0.0,
                    precision_rounding=move.product_uom.rounding,
                ) <= 0:
                    continue
                line_commands.append(Command.create({
                    'move_id': move.id,
                    'lot_id': move_line.lot_id.id,
                    'location_id': move.location_id.id,
                    'return_qty': qty_to_return,
                }))
                remaining_qty -= qty_to_return
                if float_compare(
                    remaining_qty,
                    0.0,
                    precision_rounding=move.product_uom.rounding,
                ) <= 0:
                    break
        if not line_commands:
            raise UserError(_('No excess move lines could be derived from the consumed material lines.'))
        return_order.write({'line_ids': line_commands})
        return_order.action_create_returns()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Excess Return'),
            'res_model': 'mrp.excess.return',
            'res_id': return_order.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_view_excess_returns(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'sn_wsd_mrp.action_mrp_excess_return'
        )
        if self.excess_return_count == 1:
            action['view_mode'] = 'form'
            action['res_id'] = self.excess_return_ids.id
            action['views'] = [(False, 'form')]
        else:
            action['domain'] = [('production_id', '=', self.id)]
            action['context'] = {'default_production_id': self.id}
        return action


class MrpExcessReturn(models.Model):
    _name = 'mrp.excess.return'
    _description = 'Excess Material Return'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Return Reference',
        default=lambda self: _('New'),
        copy=False,
        readonly=True,
        tracking=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
        readonly=True,
        check_company=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='production_id.company_id',
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        readonly=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        'mrp.excess.return.line',
        'return_id',
        string='Lines',
    )
    move_ids = fields.One2many(
        'stock.move',
        'excess_return_id',
        string='Stock Moves',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mrp.excess.return') or _('New')
        return super().create(vals_list)

    def action_create_returns(self):
        stock_move_model = self.env['stock.move'].with_context(mail_create_nolog=True)
        for record in self:
            if record.move_ids:
                continue
            move_ids = []
            production_location = record.production_id.product_id.with_company(
                record.company_id
            ).property_stock_production
            for line in record.line_ids.filtered(lambda item: item.return_qty > 0):
                move = stock_move_model.create({
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.return_qty,
                    'product_uom': line.return_uom_id.id,
                    'location_id': production_location.id,
                    'location_dest_id': line.location_id.id,
                    'company_id': record.company_id.id,
                    'picking_type_id': record.production_id.picking_type_id.id,
                    'origin': record.production_id.name,
                    'excess_return_id': record.id,
                    'move_line_ids': [Command.create({
                        'product_id': line.product_id.id,
                        'product_uom_id': line.return_uom_id.id,
                        'quantity': line.return_qty,
                        'lot_id': line.lot_id.id,
                        'location_id': production_location.id,
                        'location_dest_id': line.location_id.id,
                        'company_id': record.company_id.id,
                    })],
                })
                move_ids.append(move.id)
            if move_ids:
                record.move_ids = [Command.set(move_ids)]
        return True

    def action_confirm(self):
        for record in self:
            if not record.move_ids:
                record.action_create_returns()
            moves = record.move_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
            moves._action_confirm(merge=False)
            moves.picked = True
            moves._action_done()
            record.state = 'done'
        return True

    def action_cancel(self):
        self.filtered(lambda record: record.state == 'draft').write({'state': 'cancelled'})
        return True


class MrpExcessReturnLine(models.Model):
    _name = 'mrp.excess.return.line'
    _description = 'Excess Material Return Line'
    _order = 'return_id, id'
    _check_company_auto = True

    return_id = fields.Many2one(
        'mrp.excess.return',
        string='Return',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='return_id.company_id',
        store=True,
        readonly=True,
    )
    move_id = fields.Many2one(
        'stock.move',
        string='Source Move',
        required=True,
        check_company=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        related='move_id.product_id',
        store=True,
        readonly=True,
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lot',
        check_company=True,
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Return Location',
        required=True,
        check_company=True,
    )
    picked_qty = fields.Float(
        string='Picked Qty',
        related='move_id.product_uom_qty',
        readonly=True,
    )
    consumed_qty = fields.Float(
        string='Consumed Qty',
        related='move_id.quantity',
        readonly=True,
    )
    return_qty = fields.Float(
        string='Return Qty',
        digits='Product Unit',
        compute='_compute_return_qty',
        store=True,
        readonly=False,
    )
    return_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        related='move_id.product_uom',
        store=True,
        readonly=True,
    )

    @api.depends('picked_qty', 'consumed_qty')
    def _compute_return_qty(self):
        for line in self:
            line.return_qty = max(0.0, line.picked_qty - line.consumed_qty)

    @api.constrains('return_qty')
    def _check_return_qty(self):
        for line in self:
            if float_compare(
                line.return_qty,
                line.picked_qty - line.consumed_qty,
                precision_rounding=line.return_uom_id.rounding or 0.01,
            ) > 0:
                raise ValidationError(_('Return quantity cannot exceed excess quantity.'))


class MrpSubstituteUsage(models.Model):
    _name = 'mrp.substitute.usage'
    _description = 'Substitute Material Usage'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        default=lambda self: _('New'),
        copy=False,
        readonly=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
        readonly=True,
        check_company=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Route Operation',
        readonly=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='production_id.company_id',
        store=True,
        readonly=True,
    )
    bom_id = fields.Many2one(
        'mrp.bom',
        string='BoM',
        readonly=True,
        check_company=True,
    )
    bom_line_id = fields.Many2one(
        'mrp.bom.line',
        string='BoM Line',
        readonly=True,
        check_company=True,
    )
    substitute_bom_line_id = fields.Many2one(
        'mrp.bom.line',
        string='Substitute BoM Line',
        readonly=True,
        check_company=True,
    )
    original_product_id = fields.Many2one(
        'product.product',
        string='Original Product',
        required=True,
        readonly=True,
        check_company=True,
    )
    original_lot_id = fields.Many2one(
        'stock.lot',
        string='Original Lot',
        readonly=True,
        check_company=True,
    )
    substitute_product_id = fields.Many2one(
        'product.product',
        string='Substitute Product',
        required=True,
        readonly=True,
        check_company=True,
    )
    substitute_lot_id = fields.Many2one(
        'stock.lot',
        string='Substitute Lot',
        readonly=True,
        check_company=True,
    )
    original_uom_qty = fields.Float(
        string='Original Qty',
        readonly=True,
    )
    substitute_uom_qty = fields.Float(
        string='Substitute Qty',
        required=True,
        readonly=True,
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        related='original_product_id.uom_id',
        store=True,
        readonly=True,
    )
    approved_by = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
    )
    approved_date = fields.Datetime(
        string='Approved On',
        readonly=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string='Status',
        default='draft',
        readonly=True,
    )
    consume_move_line_id = fields.Many2one(
        'stock.move.line',
        string='Consumed Move Line',
        readonly=True,
        check_company=True,
    )
    note = fields.Text(string='Note')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mrp.substitute.usage') or _('New')
        return super().create(vals_list)


class MrpFeederLine(models.Model):
    _name = 'mrp.feeder.line'
    _description = 'SMT Feeder Setup Record'
    _order = 'route_operation_id, feeder_no, id'
    _rec_name = 'display_name'
    _check_company_auto = True

    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Route Operation',
        required=True,
        index=True,
        check_company=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='production_id.company_id',
        store=True,
        readonly=True,
    )
    source_move_id = fields.Many2one(
        'stock.move',
        string='Source Raw Move',
        check_company=True,
    )
    feeder_no = fields.Char(
        string='Feeder No',
        required=True,
    )
    expected_product_id = fields.Many2one(
        'product.product',
        string='Expected Product',
        required=True,
        check_company=True,
    )
    expected_product_code = fields.Char(
        string='Expected Code',
        related='expected_product_id.default_code',
        readonly=True,
    )
    expected_qty = fields.Float(
        string='Expected Qty',
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        related='expected_product_id.uom_id',
        store=True,
        readonly=True,
    )
    actual_product_id = fields.Many2one(
        'product.product',
        string='Actual Product',
        readonly=True,
        check_company=True,
    )
    actual_product_code = fields.Char(
        string='Actual Code',
        related='actual_product_id.default_code',
        readonly=True,
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lot',
        readonly=True,
        check_company=True,
    )
    lot_name = fields.Char(
        string='Lot Name',
        readonly=True,
    )
    loaded_qty = fields.Float(
        string='Loaded Qty',
        readonly=True,
    )
    consumed_qty = fields.Float(
        string='Consumed Qty',
        readonly=True,
        default=0.0,
    )
    scrap_qty = fields.Float(
        string='Scrap Qty',
        readonly=True,
        default=0.0,
    )
    remaining_qty = fields.Float(
        string='Remaining Qty',
        compute='_compute_remaining_qty',
    )
    verify_datetime = fields.Datetime(
        string='Verified On',
        readonly=True,
    )
    verify_user_id = fields.Many2one(
        'res.users',
        string='Verified By',
        readonly=True,
    )
    unload_datetime = fields.Datetime(
        string='Unload Time',
        readonly=True,
    )
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('verified', 'Verified'),
            ('consuming', 'Consuming'),
            ('depleted', 'Depleted'),
            ('returned', 'Returned'),
        ],
        string='Status',
        default='pending',
        required=True,
        readonly=True,
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
    )

    @api.depends('feeder_no', 'expected_product_id.display_name')
    def _compute_display_name(self):
        for line in self:
            line.display_name = ' - '.join(
                item for item in [line.feeder_no, line.expected_product_id.display_name] if item
            )

    @api.depends('loaded_qty', 'consumed_qty', 'scrap_qty')
    def _compute_remaining_qty(self):
        for line in self:
            line.remaining_qty = line.loaded_qty - line.consumed_qty - line.scrap_qty

    def action_scan_feeder(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Feeder Scan'),
            'res_model': 'mrp.feeder.scan.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_feeder_line_id': self.id,
            },
        }
