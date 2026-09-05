from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    can_print_material_labels = fields.Boolean(
        string='Can Print Material Labels',
        compute='_compute_can_print_material_labels',
    )

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
        )
        if lots:
            action = self.env.ref(
                'sn_wsd_stock.action_report_incoming_material_label_zpl'
            ).report_action(lots, config=False)
            action['close_on_report_download'] = True
            return action
        raise UserError(
            _('Generate internal batches from the move details before printing material labels.')
        )

    def button_validate(self):
        for picking in self:
            if picking.picking_type_code != 'incoming':
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

    def action_generate_material_labels(self):
        self.ensure_one()
        if (
            self.picking_code != 'incoming'
            or self.state in ('done', 'cancel')
            or self.product_id.tracking != 'lot'
        ):
            raise UserError(
                _('Material labels can only be generated for active incoming lot moves.')
            )
        if not self.picking_id.partner_id.ref:
            raise ValidationError(
                _('A supplier reference code is required to generate material labels.')
            )
        move_lines = self.move_line_ids.filtered(
            lambda line: line.quantity > 0 and not line.lot_id
        ).sorted('id')
        existing_lots = self.move_line_ids.lot_id.filtered(
            lambda lot: lot.material_sn_base
        )
        for move_line in move_lines.filtered(
            lambda line: not line.supplier_batch_no and line.lot_name
        ):
            move_line.supplier_batch_no = move_line.lot_name
        if not move_lines:
            if existing_lots:
                raise ValidationError(
                    _('Internal batches have already been generated for this move.')
                )
            raise ValidationError(_('There are no material lines to generate.'))
        if any(not (line.supplier_batch_no or '').strip() for line in move_lines):
            raise ValidationError(
                _('Enter a supplier batch for every line before generating material labels.')
            )
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
        )
        if not lots:
            raise UserError(
                _('Generate internal batches before printing material labels.')
            )
        action = self.env.ref(
            'sn_wsd_stock.action_report_incoming_material_label_zpl'
        ).report_action(lots, config=False)
        return action

    def _generate_material_lots_from_move_line(self, move_line):
        self.ensure_one()
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
                'supplier_code': self.picking_id.partner_id.ref,
                'supplier_name': self.picking_id.partner_id.name,
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
        supplier_code = (self.picking_id.partner_id.ref or '').strip()
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
        return {
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
            'location_dest_id': source_line.location_dest_id.id,
            'package_id': source_line.package_id.id,
            'result_package_id': source_line.result_package_id.id,
            'owner_id': source_line.owner_id.id,
        }


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

    @api.onchange('quantity')
    def _onchange_quantity_per_label(self):
        for line in self:
            if not line.quantity_per_label:
                line.quantity_per_label = line.quantity_product_uom

    def _sync_material_lot_quantity(self):
        for line in self.filtered(
            lambda item: item.lot_id
            and item.lot_id.material_sn_base
            and item.product_id.tracking == 'lot'
        ):
            lot = line.lot_id
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
