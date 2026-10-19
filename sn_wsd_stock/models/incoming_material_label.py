from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    can_print_material_labels = fields.Boolean(
        string='Can Print Material Labels',
        compute='_compute_can_print_material_labels',
    )
    # 表单按钮可见性用（modifier 不支持 picking_type_id.sequence_code
    # 点路径，收敛为布尔）
    is_mes_receipt = fields.Boolean(
        string='Is MES Completion Receipt',
        compute='_compute_is_mes_receipt',
    )

    def _compute_is_mes_receipt(self):
        for picking in self:
            picking.is_mes_receipt = (
                picking.picking_type_id.sequence_code
                == 'sn.wsd.mes.picking.receipt')

    def _compute_can_print_material_labels(self):
        for picking in self:
            has_tracked = any(
                move.product_id and move.product_id.tracking == 'lot'
                for move in picking.move_ids
            )
            picking.can_print_material_labels = (
                picking.state != 'cancel' and has_tracked
            )

    def action_open_material_label_wizard(self):
        """Keep the former public method for dependent addons without reopening its wizard."""
        self.ensure_one()
        if self.picking_type_id.sequence_code == 'sn.wsd.mes.picking.receipt':
            return self.action_print_finished_material_labels()

        lots = self.move_line_ids.lot_id.filtered(
            lambda lot: lot.material_sn_base
        ).sorted(key=lambda lot: (lot.material_sn_base or lot.name or '', lot.id))
        if lots:
            action = self.env.ref(
                'sn_wsd_stock.action_report_incoming_material_label_zpl'
            ).report_action(lots, config=False)
            action['close_on_report_download'] = True
            return action
        raise UserError(
            _('Generate internal batches from the move details before printing material labels.')
        )

    def _is_final_receipt_picking(self):
        """Operation that stores the received goods in the final stock location.

        Tracked material must carry an internal batch before it reaches stock:
        with a three-step reception the storage transfer (quality -> stock)
        enforces it, otherwise the receipt does. Material labels may however be
        generated earlier, on the receipt itself.
        """
        self.ensure_one()
        picking_type = self.picking_type_id
        warehouse = picking_type.warehouse_id
        store_type = warehouse.store_type_id if warehouse else False
        if store_type and store_type.active:
            return picking_type == store_type
        return picking_type.code == 'incoming'

    def button_validate(self):
        for picking in self:
            if not picking._is_final_receipt_picking():
                continue
            unlabelled_lines = picking.move_line_ids.filtered(
                lambda line: (
                    line.product_id.tracking in ('lot', 'serial')
                    and line.quantity > 0
                    and not line.lot_id
                )
            )
            if unlabelled_lines:
                raise UserError(
                    _(
                        'Generate material labels before validating tracked '
                        'products: %(products)s',
                        products=', '.join(
                            unlabelled_lines.mapped('product_id.display_name')
                        ),
                    )
                )
        return super().button_validate()


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_can_generate_material_labels = fields.Boolean(
        string='Can Generate Material Labels',
        compute='_compute_x_can_generate_material_labels',
    )

    @api.depends('picking_id.picking_type_id', 'picking_id.state',
                 'product_id.tracking', 'state')
    def _compute_x_can_generate_material_labels(self):
        for move in self:
            move.x_can_generate_material_labels = move._is_material_label_picking()

    def _is_material_label_picking(self):
        """Whether material labels may be generated from this move.

        Labels are generated on the operation that stores the goods in stock:
        the receipt itself with a one-step reception, the storage transfer
        (quality/input -> stock) with two- or three-step receptions. The
        quantity per label that splits a line into several internal batches is
        decided on that operation, together with the rack allocation, so the
        upstream receipt and quality control transfers must not create
        batches: their lots would reach the storage transfer on the quants and
        could no longer be re-split.
        """
        self.ensure_one()
        picking = self.picking_id
        if (
            not picking
            or self.state in ('done', 'cancel')
            or self.product_id.tracking != 'lot'
        ):
            return False
        return picking._is_final_receipt_picking()

    def _get_material_supplier_picking(self):
        """Receipt carrying the supplier reference for this move.

        A three-step storage transfer has no supplier of its own, so the
        reference is looked up through the upstream moves.
        """
        self.ensure_one()
        picking = self.picking_id
        if picking.picking_type_code == 'incoming' or picking.partner_id.ref:
            return picking
        visited = self.env['stock.move']
        pending = self
        while pending:
            origins = pending.move_orig_ids - visited
            if not origins:
                break
            visited |= origins
            incoming = origins.filtered(
                lambda move: move.picking_id.picking_type_code == 'incoming'
                and move.picking_id.partner_id.ref
            )
            if incoming:
                return incoming.picking_id[:1]
            pending = origins
        return picking

    def action_generate_material_labels(self):
        self.ensure_one()
        if not self._is_material_label_picking():
            raise UserError(
                _('Material labels can only be generated for active receipt or storage lot moves.')
            )
        supplier_picking = self._get_material_supplier_picking()
        if not supplier_picking.partner_id.ref:
            raise ValidationError(
                _('A supplier reference code is required to generate material labels.')
            )
        move_lines = self.move_line_ids.filtered(
            lambda line: line.quantity > 0 and not line.lot_id
        ).sorted('id')
        existing_lots = self.move_line_ids.lot_id.filtered(
            lambda lot: lot.material_sn_base
        )
        today = fields.Date.context_today(self).strftime('%Y%m%d')
        for move_line in move_lines.filtered(
            lambda line: not (line.supplier_batch_no or '').strip()
        ):
            # The supplier batch is the batch segment of the material SN: fall
            # back to the internal batch name typed on the line, then to the
            # arrival date, so a receipt without a supplier batch never blocks
            # the label generation.
            move_line.supplier_batch_no = move_line.lot_name or today
        if not move_lines:
            if existing_lots:
                raise ValidationError(
                    _('Internal batches have already been generated for this move.')
                )
            raise ValidationError(_('There are no material lines to generate.'))
        if any(line.quantity_per_label <= 0 for line in move_lines):
            raise ValidationError(
                _('Enter a quantity per label greater than zero for every line before generating material labels.')
            )

        lots = self.env['stock.lot']
        for move_line in move_lines:
            lots |= self._generate_material_lots_from_move_line(move_line)
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_stock.refresh_current_view',
        }

    def action_print_material_labels(self):
        self.ensure_one()
        lots = self.move_line_ids.lot_id.filtered(
            lambda lot: lot.material_sn_base
        ).sorted(key=lambda lot: (lot.material_sn_base or lot.name or '', lot.id))
        if not lots:
            raise UserError(
                _('Generate internal batches before printing material labels.')
            )
        action = self.env.ref(
            'sn_wsd_stock.action_report_incoming_material_label_zpl'
        ).report_action(lots, config=False)
        return action

    def action_revoke_material_labels(self):
        """Remove the internal batches generated on this operation.

        The operator may have entered a wrong quantity per label: the batches
        have to be removed before the split can be redone. Only batches
        created by this flow that were never printed nor consumed qualify; the
        lines are merged back into one and the lots deleted.
        """
        self.ensure_one()
        if not self._is_material_label_picking():
            raise UserError(_(
                'Internal batches can only be revoked on an open storage operation.'
            ))
        lines = self.move_line_ids.filtered('lot_id')
        if not lines:
            raise UserError(_('There are no internal batches to revoke on this move.'))
        lots = lines.lot_id
        foreign_lots = lots.filtered(lambda lot: not lot.material_sn_base)
        if foreign_lots:
            raise UserError(_(
                'The operation lines carry a lot that was not generated by the material label flow: %s',
                ', '.join(foreign_lots.mapped('name')),
            ))
        other_lines = self.env['stock.move.line'].search([
            ('lot_id', 'in', lots.ids),
            ('id', 'not in', lines.ids),
            ('state', 'not in', ('done', 'cancel')),
        ])
        quants = self.env['stock.quant'].search([('lot_id', 'in', lots.ids)])
        consumed_quants = quants.filtered(lambda quant: quant.quantity > 0)
        blocked_lots = (
            lots.filtered('label_print_count')
            | other_lines.lot_id
            | consumed_quants.lot_id
        )
        if blocked_lots:
            raise UserError(_(
                'Internal batches that were already printed or consumed cannot be revoked: %s',
                ', '.join(blocked_lots.mapped('name')),
            ))

        first_line = lines.sorted('id')[:1]
        first_line.write({
            'quantity': sum(lines.mapped('quantity')),
            'lot_id': False,
            'lot_name': False,
            'material_sn_base': False,
            'material_sn_suffix': False,
            'material_label_printed': False,
        })
        (lines - first_line).unlink()
        # Setting the lot on a line also synchronizes the reservation, which
        # may leave an empty quant behind: it has no quantity, so it is only
        # an obstacle for the lot deletion.
        quants.unlink()
        lots.unlink()
        if (
            'picklight_allocation_state' in first_line._fields
            and first_line.picklight_allocation_state == 'auto'
        ):
            default_location = (
                self.location_dest_id or first_line.picking_id.location_dest_id
            )
            first_line.with_context(picklight_allocation_write=True).write({
                'location_dest_id': default_location.id,
                'picklight_allocation_state': 'none',
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_stock.refresh_current_view',
        }

    def _generate_material_lots_from_move_line(self, move_line):
        self.ensure_one()
        supplier_picking = self._get_material_supplier_picking()
        batch_no = (move_line.supplier_batch_no or '').strip()
        if '$' in batch_no:
            raise ValidationError(_('The supplier batch cannot contain the $ character.'))
        quantities = self._get_label_quantities(move_line)
        lot_values = []
        move_line_values = []
        for quantity in quantities:
            sequence = self.env['ir.sequence'].next_by_code(
                'sn.wsd.material.serial'
            )
            if not sequence:
                raise UserError(_('The material serial sequence is not configured.'))
            lot_name = self._get_material_sn(batch_no, quantity, sequence)
            if self.env['stock.lot'].search_count([
                ('name', '=', lot_name),
                ('product_id', '=', self.product_id.id),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', self.company_id.id),
            ]):
                raise ValidationError(_('The material SN already exists: %s', lot_name))
            lot_values.append({
                'name': lot_name,
                'product_id': self.product_id.id,
                'company_id': self.company_id.id,
                'arrival_batch_no': fields.Date.context_today(self).strftime('%Y%m%d'),
                'material_sn_base': lot_name,
                'supplier_code': supplier_picking.partner_id.ref,
                'supplier_name': supplier_picking.partner_id.name,
                'supplier_batch_no': batch_no,
                'initial_quantity': quantity,
                'source_picking_id': self.picking_id.id,
                'source_move_line_id': move_line.id,
            })
            move_line_values.append((lot_name, quantity))
        lots = self.env['stock.lot'].create(lot_values)
        generated_values = [
            self._prepare_generated_move_line_values(
                move_line, lot, quantity, batch_no,
            )
            for lot, (_, quantity) in zip(lots, move_line_values)
        ]
        move_line.write(generated_values[0])
        if len(generated_values) > 1:
            self.env['stock.move.line'].create(generated_values[1:])
        return lots

    def _get_label_quantities(self, move_line):
        total_quantity = move_line.quantity_product_uom
        quantity_per_label = move_line.quantity_per_label
        if quantity_per_label > total_quantity:
            raise ValidationError(
                _('Quantity per label cannot exceed the total quantity.')
            )
        quantities = []
        remaining = total_quantity
        while remaining > quantity_per_label:
            quantities.append(quantity_per_label)
            remaining -= quantity_per_label
        if not float_is_zero(
            remaining, precision_rounding=self.product_id.uom_id.rounding,
        ):
            quantities.append(remaining)
        return quantities

    def _get_material_sn(self, batch_no, quantity, sequence):
        product_code = (self.product_id.default_code or '').strip()
        supplier_code = (self._get_material_supplier_picking().partner_id.ref or '').strip()
        if not product_code:
            raise ValidationError(_(
                'Product %(product)s must have an internal reference.',
                product=self.product_id.display_name,
            ))
        return '$'.join([
            product_code, supplier_code, batch_no, str(int(quantity)), sequence,
        ])

    def _prepare_generated_move_line_values(
        self, source_line, lot, quantity, batch_no,
    ):
        location_dest_id = source_line.location_dest_id.id
        allocation_state = False
        if 'picklight_allocation_state' in source_line._fields:
            allocation_state = source_line.picklight_allocation_state
            if allocation_state == 'auto':
                # Splitting invalidates the automatic rack allocation: every
                # label needs its own location, so the operator allocates the
                # racks again once the split is done.
                location_dest_id = self.location_dest_id.id or location_dest_id
                allocation_state = 'none'
        values = {
            'move_id': self.id,
            'picking_id': self.picking_id.id,
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom_id': source_line.product_uom_id.id,
            'quantity': self.product_id.uom_id._compute_quantity(
                quantity, source_line.product_uom_id,
            ),
            'picked': source_line.picked,
            'lot_id': lot.id,
            'lot_name': lot.name,
            'supplier_batch_no': batch_no,
            'quantity_per_label': quantity,
            'material_sn_base': lot.material_sn_base,
            'material_sn_suffix': lot.material_sn_suffix,
            'material_label_printed': True,
            'location_id': source_line.location_id.id,
            'location_dest_id': location_dest_id,
            'package_id': source_line.package_id.id,
            'result_package_id': source_line.result_package_id.id,
            'owner_id': source_line.owner_id.id,
        }
        if 'picklight_allocation_state' in source_line._fields:
            values['picklight_allocation_state'] = allocation_state
        return values


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    supplier_batch_no = fields.Char(string='Supplier Batch', copy=False, index=True)
    quantity_per_label = fields.Float(
        string='Quantity per Label',
        digits='Product Unit',
        copy=False,
    )
    internal_lot_name = fields.Char(
        related='lot_id.name',
        string='Internal Batch',
        store=True,
        readonly=True,
        index=True,
    )
    material_sn_base = fields.Char(
        string='Material SN Base', copy=False, readonly=True, index=True,
    )
    material_sn_suffix = fields.Char(
        string='Material SN Suffix', copy=False, readonly=True,
    )
    material_label_printed = fields.Boolean(
        string='Material Label Printed', copy=False, readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Initialize the label quantity and the supplier batch of a new line.

        The label quantity is intentionally not recomputed when the operation
        quantity is edited later; users may choose a different quantity per
        label. The supplier batch defaults to the arrival date only on the
        operation that generates the labels: it is the batch segment of the
        material SN and is overwritten only when the supplier printed a batch
        of its own. The upstream receipt and quality control transfer stay
        empty on purpose: one line there may cover several supplier batches,
        and the value would not survive the quant merge.
        """
        today = fields.Date.context_today(self).strftime('%Y%m%d')
        for vals in vals_list:
            if 'quantity_per_label' not in vals and vals.get('quantity'):
                vals['quantity_per_label'] = vals['quantity']
            if (not (vals.get('supplier_batch_no') or '').strip()
                    and self._supplier_batch_default_applies(vals)):
                vals['supplier_batch_no'] = today
        return super().create(vals_list)

    @api.model
    def _supplier_batch_default_applies(self, vals):
        """Whether the line belongs to the operation deciding the supplier batch.

        That is the transfer storing the received goods (the receipt itself
        with a one-step reception), i.e. the operation generating the material
        labels. The receipt and the quality control transfer of a multi-step
        reception keep the field empty: the supplier batch is read from the
        reels at putaway, where the line is split per batch.
        """
        picking = self.env['stock.picking']
        if vals.get('picking_id'):
            picking = picking.browse(vals['picking_id'])
        elif vals.get('move_id'):
            picking = self.env['stock.move'].browse(vals['move_id']).picking_id
        return bool(picking) and picking._is_final_receipt_picking()

    @api.onchange('quantity')
    def _onchange_quantity_per_label(self):
        """Set the initial value for a new inline operation only.

        Existing operations retain their manually configured value when
        ``quantity`` is changed.
        """
        for line in self:
            if not line._origin and not line.quantity_per_label:
                line.quantity_per_label = line.quantity

    def _sync_material_lot_quantity(self):
        for line in self.filtered(
            lambda item: item.lot_id
            and item.lot_id.material_sn_base
            and item.product_id.tracking == 'lot'
        ):
            lot = line.lot_id
            if lot.label_print_count:
                raise ValidationError(_(
                    'The material label of %s was already printed: the quantity can no longer be changed.',
                    lot.name,
                ))
            quantity = line.product_uom_id._compute_quantity(
                line.quantity, line.product_id.uom_id,
            )
            lot_vals = {'initial_quantity': quantity}
            parts = (lot.name or '').split('$')
            if len(parts) >= 5 and parts[3].isdigit():
                parts[3] = str(int(quantity))
                new_name = '$'.join(parts)
                duplicate = self.env['stock.lot'].search([
                    ('id', '!=', lot.id),
                    ('name', '=', new_name),
                    ('product_id', '=', lot.product_id.id),
                    '|',
                    ('company_id', '=', False),
                    ('company_id', '=', lot.company_id.id),
                ], limit=1)
                if duplicate:
                    raise ValidationError(
                        _('The material SN already exists: %s', new_name)
                    )
                lot_vals.update({
                    'name': new_name,
                    'material_sn_base': new_name,
                })
            lot.write(lot_vals)
            line.write({
                'lot_name': lot.name,
                'material_sn_base': lot.material_sn_base,
            })

    def write(self, vals):
        result = super().write(vals)
        if 'quantity' in vals or 'qty_done' in vals:
            self._sync_material_lot_quantity()
        return result


class StockLot(models.Model):
    _inherit = 'stock.lot'

    arrival_batch_no = fields.Char(
        string='Arrival Batch',
        copy=False,
        readonly=True,
        index=True,
    )
    material_sn_base = fields.Char(
        string='Material SN Base', copy=False, index=True, readonly=True,
    )
    material_sn_suffix = fields.Char(
        string='Material SN Suffix', copy=False, readonly=True,
    )
    supplier_code = fields.Char(string='Supplier Code', copy=False, readonly=True)
    supplier_name = fields.Char(string='Supplier Name', copy=False, readonly=True)
    supplier_batch_no = fields.Char(
        string='Supplier Batch', copy=False, readonly=True,
    )
    initial_quantity = fields.Float(
        string='Initial Quantity', copy=False, readonly=True, digits='Product Unit',
    )
    source_picking_id = fields.Many2one(
        'stock.picking', string='Source Receipt', copy=False, readonly=True,
        index=True, check_company=True,
    )
    source_move_line_id = fields.Many2one(
        'stock.move.line', string='Source Operation Line', copy=False,
        readonly=True, index=True, check_company=True,
    )
    label_print_count = fields.Integer(
        string='Label Print Count', default=0, copy=False, readonly=True,
    )
    material_label_location = fields.Char(
        string='Material Label Location',
        compute='_compute_material_label_location',
        help='Location printed on the material label. The final path segment '
             'of the receipt destination is preferred; the current quant '
             'location is used as a fallback.',
    )

    @api.depends(
        'location_id.complete_name',
        'source_picking_id.move_line_ids.location_dest_id.complete_name',
        'source_picking_id.move_line_ids.lot_id',
        'source_move_line_id.location_dest_id.complete_name',
    )
    def _compute_material_label_location(self):
        for lot in self:
            # The location of the operation line the label was generated from is
            # preferred: on a receipt it is the input destination, on a storage
            # transfer it is the final rack.
            receipt_line = lot.source_picking_id.move_line_ids.filtered(
                lambda line: line.lot_id == lot
            )[:1]
            location_name = (
                receipt_line.location_dest_id.complete_name
                or lot.source_move_line_id.location_dest_id.complete_name
                or lot.location_id.complete_name
            )
            lot.material_label_location = (
                location_name.rsplit('/', 1)[-1].strip()
                if location_name else False
            )


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    supplier_batch_no = fields.Char(
        related='lot_id.supplier_batch_no',
        string='Supplier Batch',
        readonly=True,
    )
    arrival_batch_no = fields.Char(
        related='lot_id.arrival_batch_no',
        string='Arrival Batch',
        readonly=True,
    )
