from odoo import _, Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


class IncomingMaterialLabelWizard(models.TransientModel):
    _name = 'sn.wsd.incoming.material.label.wizard'
    _description = 'Generate and Print Material Labels'

    picking_id = fields.Many2one(
        'stock.picking', string='Receipt', required=True, readonly=True,
        check_company=True,
    )
    partner_id = fields.Many2one(
        related='picking_id.partner_id', string='Supplier', readonly=True,
    )
    supplier_code = fields.Char(
        related='partner_id.ref', string='Supplier Code', readonly=True,
    )
    line_ids = fields.One2many(
        'sn.wsd.incoming.material.label.wizard.line', 'wizard_id',
        string='Material Lines',
    )

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        picking = self.env['stock.picking'].browse(
            values.get('picking_id')
        ).exists()
        if not picking:
            return values
        selected_move_line = self.env['stock.move.line'].browse(
            self.env.context.get('default_move_line_id')
        ).exists()
        if (
            selected_move_line
            and selected_move_line.picking_id == picking
            and selected_move_line.product_id.tracking == 'lot'
        ):
            values['line_ids'] = [Command.create({
                'move_id': selected_move_line.move_id.id,
                'move_line_id': selected_move_line.id,
                'product_id': selected_move_line.product_id.id,
                'quantity': selected_move_line.quantity_product_uom,
                'quantity_per_label': selected_move_line.quantity_product_uom,
                'official_batch_no': self._get_official_batch_name(selected_move_line),
                'existing_lot_id': selected_move_line.lot_id.id,
            })]
            return values
        commands = []
        for move in picking.move_ids.filtered(
            lambda item: item.product_id and item.product_id.tracking == 'lot'
        ):
            move_lines = move.move_line_ids.filtered(
                lambda line: line.quantity > 0 or not line.lot_id
            )
            for move_line in move_lines or [self.env['stock.move.line']]:
                quantity = move_line.quantity_product_uom if move_line else 0
                if not quantity:
                    quantity = move.product_uom._compute_quantity(
                        move.product_uom_qty, move.product_id.uom_id,
                    )
                commands.append(Command.create({
                    'move_id': move.id,
                    'move_line_id': move_line.id if move_line else False,
                    'product_id': move.product_id.id,
                    'quantity': quantity,
                    'quantity_per_label': quantity,
                    'official_batch_no': self._get_official_batch_name(move_line),
                    'existing_lot_id': move_line.lot_id.id if move_line else False,
                }))
        values['line_ids'] = commands
        return values

    def _validate_header(self):
        self.ensure_one()
        if (
            self.picking_id.picking_type_code != 'incoming'
            or self.picking_id.state in ('done', 'cancel')
        ):
            raise UserError(_('Material labels can only be printed for active receipts.'))
        if not self.picking_id.partner_id.ref:
            raise ValidationError(
                _('The supplier must have a reference code before printing labels.')
            )

    @staticmethod
    def _get_official_batch_name(move_line):
        if not move_line:
            return ''
        return (move_line.lot_name or move_line.lot_id.name or '').strip()

    def _get_quantities(self, line):
        quantity = line.quantity
        quantity_per_label = line.quantity_per_label or quantity
        if quantity <= 0 or quantity_per_label <= 0:
            raise ValidationError(_('Label quantities must be greater than zero.'))
        if quantity_per_label > quantity:
            raise ValidationError(
                _('Quantity per label cannot exceed the total quantity.')
            )
        quantities = []
        remaining = quantity
        while remaining > quantity_per_label:
            quantities.append(quantity_per_label)
            remaining -= quantity_per_label
        if not float_is_zero(
            remaining, precision_rounding=line.product_id.uom_id.rounding
        ):
            quantities.append(remaining)
        return quantities or [quantity]

    def _get_existing_material_lot(self, line):
        source_line = line.move_line_id
        if not source_line:
            return self.env['stock.lot']
        lot = source_line.lot_id
        if lot and lot.material_sn_base:
            return lot
        lot_name = self._get_official_batch_name(source_line)
        if not lot_name:
            return self.env['stock.lot']
        return self.env['stock.lot'].search([
            ('name', '=', lot_name),
            ('product_id', '=', line.product_id.id),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.picking_id.company_id.id),
            ('material_sn_base', '!=', False),
        ], limit=1)

    def _get_material_sn(self, line, batch_no, quantity, sequence):
        product_code = (line.product_id.default_code or '').strip()
        supplier_code = (self.picking_id.partner_id.ref or '').strip()
        if not product_code:
            raise ValidationError(_(
                'Product %(product)s must have an internal reference.',
                product=line.product_id.display_name,
            ))
        material_sn = '$'.join([
            product_code, supplier_code, batch_no, str(int(quantity)), sequence,
        ])
        return material_sn

    def _create_lot(self, line, batch_no, material_sn, quantity):
        return self.env['stock.lot'].create({
            'name': material_sn,
            'product_id': line.product_id.id,
            'company_id': self.picking_id.company_id.id,
            'arrival_batch_no': fields.Date.context_today(
                self.picking_id
            ).strftime('%Y%m%d'),
            'material_sn_base': material_sn,
            'material_sn_suffix': False,
            'supplier_code': self.picking_id.partner_id.ref,
            'supplier_name': self.picking_id.partner_id.name,
            'supplier_batch_no': batch_no,
            'initial_quantity': quantity,
            'source_picking_id': self.picking_id.id,
            'source_move_line_id': line.move_line_id.id,
        })

    def _process_line(self, line, lots):
        source_line = line.move_line_id
        existing_material_lot = self._get_existing_material_lot(line)
        if existing_material_lot:
            if source_line and source_line.lot_id != existing_material_lot:
                source_line.write({
                    'lot_id': existing_material_lot.id,
                    'lot_name': existing_material_lot.name,
                })
            return lots | existing_material_lot
        if not source_line:
            move = line.move_id
            source_line = self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': self.picking_id.id,
                'company_id': self.picking_id.company_id.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'quantity': move.product_uom._compute_quantity(
                    line.quantity, move.product_uom,
                ),
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
            })
            line.move_line_id = source_line
        batch_no = (
            (line.official_batch_no or '').strip()
            or (source_line.supplier_batch_no or '').strip()
            or self._get_official_batch_name(source_line)
            or fields.Date.context_today(self.picking_id).strftime('%Y%m%d')
        )
        if '$' in batch_no:
            raise ValidationError(
                _('The supplier batch cannot contain the $ character.')
            )
        source_line.supplier_batch_no = batch_no
        created_lines = []
        quantities = self._get_quantities(line)
        for quantity in quantities:
            sequence = self.env['ir.sequence'].next_by_code(
                'sn.wsd.material.serial'
            )
            if not sequence:
                raise UserError(_('The material serial sequence is not configured.'))
            lot_name = self._get_material_sn(
                line, batch_no, quantity, sequence,
            )
            if self.env['stock.lot'].search_count([
                ('name', '=', lot_name),
                ('product_id', '=', line.product_id.id),
                '|', ('company_id', '=', False),
                ('company_id', '=', self.picking_id.company_id.id),
            ]):
                raise ValidationError(_('The material SN already exists: %s', lot_name))
            lot = self._create_lot(line, batch_no, lot_name, quantity)
            lots |= lot
            created_lines.append({
                'move_id': source_line.move_id.id,
                'picking_id': self.picking_id.id,
                'company_id': source_line.company_id.id,
                'product_id': source_line.product_id.id,
                'product_uom_id': source_line.product_uom_id.id,
                'quantity': source_line.product_id.uom_id._compute_quantity(
                    quantity, source_line.product_uom_id,
                ),
                'picked': source_line.picked,
                'lot_id': lot.id,
                'lot_name': lot.name,
                'supplier_batch_no': batch_no,
                'material_sn_base': lot.material_sn_base,
                'material_sn_suffix': lot.material_sn_suffix,
                'material_label_printed': True,
                'location_id': source_line.location_id.id,
                'location_dest_id': source_line.location_dest_id.id,
                'package_id': source_line.package_id.id,
                'result_package_id': source_line.result_package_id.id,
                'owner_id': source_line.owner_id.id,
            })
        source_line.write(created_lines[0])
        if len(created_lines) > 1:
            self.env['stock.move.line'].create(created_lines[1:])
        return lots

    def action_confirm(self):
        self.ensure_one()
        self._validate_header()
        lines = self.line_ids.filtered(
            lambda line: line.move_id and line.product_id and line.quantity > 0
        )
        if not lines:
            raise ValidationError(_('There are no material lines to print.'))
        lots = self.env['stock.lot']
        for line in lines:
            lots = self._process_line(line, lots)
        if not lots:
            raise ValidationError(_('There are no material lots to print.'))
        action = self.env.ref(
            'sn_wsd_stock.action_report_incoming_material_label_zpl'
        ).report_action(lots, config=False)
        action['close_on_report_download'] = True
        return action


class IncomingMaterialLabelWizardLine(models.TransientModel):
    _name = 'sn.wsd.incoming.material.label.wizard.line'
    _description = 'Incoming Material Label Line'
    _check_company_auto = True

    wizard_id = fields.Many2one(
        'sn.wsd.incoming.material.label.wizard', required=True,
        ondelete='cascade',
    )
    move_line_id = fields.Many2one(
        'stock.move.line', string='Operation Line', readonly=True,
        check_company=True,
    )
    move_id = fields.Many2one(
        'stock.move', string='Stock Move', readonly=True, check_company=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Product', readonly=True,
    )
    quantity = fields.Float(
        string='Quantity', readonly=True, digits='Product Unit',
    )
    quantity_per_label = fields.Float(
        string='Quantity per Label', digits='Product Unit',
    )
    official_batch_no = fields.Char(string='Supplier Batch')
    existing_lot_id = fields.Many2one(
        'stock.lot', string='Official Lot', readonly=True, check_company=True,
    )
