from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


class IncomingMaterialLabelWizard(models.TransientModel):
    _name = 'sn.wsd.incoming.material.label.wizard'
    _description = 'Generate and Print Material Labels'

    picking_id = fields.Many2one(
        'stock.picking',
        string='Receipt',
        required=True,
        readonly=True,
        check_company=True,
    )
    partner_id = fields.Many2one(
        related='picking_id.partner_id',
        string='Supplier',
        readonly=True,
    )
    supplier_code = fields.Char(
        related='partner_id.ref',
        string='Supplier Code',
        readonly=True,
    )
    line_ids = fields.One2many(
        'sn.wsd.incoming.material.label.wizard.line',
        'wizard_id',
        string='Material Lines',
    )

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        picking = self.env['stock.picking'].browse(values.get('picking_id')).exists()
        if not picking:
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
                        move.product_uom_qty,
                        move.product_id.uom_id,
                    )
                package_quantity = move.packaging_uom_id._compute_quantity(
                    1.0,
                    move.product_uom,
                )
                package_quantity = move.product_uom._compute_quantity(
                    package_quantity,
                    move.product_id.uom_id,
                )
                quantity_per_label = (
                    package_quantity
                    if move.packaging_uom_id != move.product_uom
                    and package_quantity
                    and package_quantity < quantity
                    else quantity
                )
                commands.append(Command.create({
                    'move_id': move.id,
                    'move_line_id': move_line.id if move_line else False,
                    'product_id': move.product_id.id,
                    'quantity': quantity,
                    'quantity_per_label': quantity_per_label,
                    'official_batch_no': self._get_official_batch_name(move_line),
                    'existing_lot_id': move_line.lot_id.id if move_line else False,
                }))
        values['line_ids'] = commands
        return values

    def _validate_header(self):
        self.ensure_one()
        picking = self.picking_id
        if picking.picking_type_code != 'incoming' or picking.state in ('done', 'cancel'):
            raise UserError(_('Material labels can only be printed for active receipts.'))
        if not picking.partner_id.ref:
            raise ValidationError(_('The supplier must have a reference code before printing labels.'))

    @staticmethod
    def _get_official_batch_name(move_line):
        if not move_line:
            return ''
        return (move_line.lot_name or move_line.lot_id.name or '').strip()

    def _get_supplier_batch(self, line):
        batch_no = self._get_official_batch_name(line.move_line_id)
        if not batch_no:
            batch_no = fields.Date.context_today(self.picking_id).strftime('%Y%m%d')
        return batch_no

    def _validate_batch(self, batch_no):
        if '$' in batch_no:
            raise ValidationError(_('The supplier batch cannot contain the $ character.'))

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

    def _get_material_sn(self, line, batch_no, quantity, sequence, suffix=False):
        product_code = (line.product_id.default_code or '').strip()
        supplier_code = (self.picking_id.partner_id.ref or '').strip()
        if not product_code:
            raise ValidationError(_(
                'Product %(product)s must have an internal reference.',
                product=line.product_id.display_name,
            ))
        material_sn = '$'.join([
            product_code,
            supplier_code,
            batch_no,
            str(int(quantity)),
            sequence,
        ])
        return f'{material_sn}-{suffix}' if suffix else material_sn

    def _get_quantities(self, line):
        quantity = line.quantity
        quantity_per_label = line.quantity_per_label or quantity
        if quantity <= 0 or quantity_per_label <= 0:
            raise ValidationError(_('Label quantities must be greater than zero.'))
        if quantity_per_label > quantity:
            raise ValidationError(_('Quantity per label cannot exceed the total quantity.'))
        quantities = []
        remaining = quantity
        while remaining > quantity_per_label:
            quantities.append(quantity_per_label)
            remaining -= quantity_per_label
        if not float_is_zero(remaining, precision_rounding=line.product_id.uom_id.rounding):
            quantities.append(remaining)
        return quantities or [quantity]

    def _create_lot(self, line, batch_no, material_sn, quantity, sequence, suffix):
        base_sn = material_sn.rsplit('-', 1)[0] if suffix else material_sn
        return self.env['stock.lot'].create({
            'name': material_sn,
            'product_id': line.product_id.id,
            'company_id': self.picking_id.company_id.id,
            'material_sn_base': base_sn,
            'material_sn_suffix': str(suffix) if suffix else False,
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
            lots |= existing_material_lot
            return lots
        if not source_line:
            move = line.move_id
            source_line = self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': self.picking_id.id,
                'company_id': self.picking_id.company_id.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'quantity': move.product_uom._compute_quantity(
                    line.quantity,
                    move.product_uom,
                ),
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
            })
        source_move_line_id = source_line.id

        batch_no = self._get_supplier_batch(line)
        self._validate_batch(batch_no)
        quantities = self._get_quantities(line)
        sequence = self.env['ir.sequence'].next_by_code('sn.wsd.material.serial')
        if not sequence:
            raise UserError(_('The material serial sequence is not configured.'))
        created_lines = []
        for index, quantity in enumerate(quantities, start=1):
            suffix = index if len(quantities) > 1 else False
            lot_name = self._get_material_sn(
                line, batch_no, quantity, sequence, suffix=suffix,
            )
            existing_lot = self.env['stock.lot'].search([
                ('name', '=', lot_name),
                ('product_id', '=', line.product_id.id),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', self.picking_id.company_id.id),
            ], limit=1)
            if existing_lot:
                raise ValidationError(_('The material SN already exists: %s', lot_name))
            lot = self._create_lot(
                line, batch_no, lot_name, quantity, sequence, suffix,
            )
            lot.source_move_line_id = source_move_line_id
            lots |= lot
            line_uom = source_line.product_uom_id
            created_lines.append({
                'move_id': source_line.move_id.id,
                'picking_id': self.picking_id.id,
                'company_id': source_line.company_id.id,
                'product_id': source_line.product_id.id,
                'product_uom_id': line_uom.id,
                'quantity': source_line.product_id.uom_id._compute_quantity(
                    quantity, line_uom,
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
        source_line.write({
            **created_lines[0],
            'lot_name': created_lines[0]['lot_name'],
        })
        if len(created_lines) > 1:
            self.env['stock.move.line'].create(created_lines[1:])
        return lots

    def _sync_material_lots_to_operation_lines(self, lots):
        self.ensure_one()
        operation_lines = self.picking_id.move_line_ids.filtered(
            lambda line: line.product_id.tracking == 'lot'
            and line.lot_id
            and line.lot_id in lots
        )
        operation_lines.write({
            'lot_name': False,
        })
        for operation_line in operation_lines:
            operation_line.lot_name = operation_line.lot_id.name

    def action_confirm(self):
        self.ensure_one()
        self._validate_header()
        lines = self.line_ids.filtered(
            lambda line: line.move_id and line.product_id and line.quantity > 0
        )
        if not lines:
            lines = self._rebuild_lines_from_picking()
        if not lines:
            raise ValidationError(_('There are no material lines to print.'))
        lots = self.env['stock.lot']
        for line in lines:
            lots = self._process_line(line, lots)
        if not lots:
            raise ValidationError(_('There are no material lots to print.'))
        self._sync_material_lots_to_operation_lines(lots)
        report = self.env.ref('sn_wsd_print.action_report_incoming_material_label_zpl')
        action = report.report_action(lots, config=False)
        action['close_on_report_download'] = True
        return action

    def _rebuild_lines_from_picking(self):
        self.ensure_one()
        valid_lines = self.env['sn.wsd.incoming.material.label.wizard.line']
        for move in self.picking_id.move_ids.filtered(
            lambda item: item.product_id and item.product_id.tracking == 'lot'
        ):
            move_lines = move.move_line_ids.filtered(
                lambda line: line.quantity > 0 or not line.lot_id
            )
            if not move_lines:
                move_lines = self.env['stock.move.line']
            for move_line in move_lines or [self.env['stock.move.line']]:
                quantity = move_line.quantity_product_uom if move_line else 0
                if not quantity:
                    quantity = move.product_uom._compute_quantity(
                        move.product_uom_qty,
                        move.product_id.uom_id,
                    )
                quantity_per_label = quantity
                if move.packaging_uom_id:
                    package_quantity = move.packaging_uom_id._compute_quantity(
                        1.0,
                        move.product_uom,
                    )
                    package_quantity = move.product_uom._compute_quantity(
                        package_quantity,
                        move.product_id.uom_id,
                    )
                    if package_quantity and package_quantity < quantity:
                        quantity_per_label = package_quantity
                valid_lines |= self.env[
                    'sn.wsd.incoming.material.label.wizard.line'
                ].create({
                    'wizard_id': self.id,
                    'move_id': move.id,
                    'move_line_id': move_line.id if move_line else False,
                    'product_id': move.product_id.id,
                    'quantity': quantity,
                    'quantity_per_label': quantity_per_label,
                    'official_batch_no': self._get_official_batch_name(move_line),
                    'existing_lot_id': move_line.lot_id.id if move_line else False,
                })
        return valid_lines


class IncomingMaterialLabelWizardLine(models.TransientModel):
    _name = 'sn.wsd.incoming.material.label.wizard.line'
    _description = 'Incoming Material Label Line'
    _check_company_auto = True

    wizard_id = fields.Many2one(
        'sn.wsd.incoming.material.label.wizard',
        required=True,
        ondelete='cascade',
    )
    move_line_id = fields.Many2one(
        'stock.move.line',
        string='Operation Line',
        readonly=True,
        check_company=True,
    )
    move_id = fields.Many2one(
        'stock.move',
        string='Stock Move',
        readonly=True,
        check_company=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        readonly=True,
    )
    quantity = fields.Float(
        string='Quantity',
        readonly=True,
        digits='Product Unit',
    )
    quantity_per_label = fields.Float(
        string='Quantity per Label',
        digits='Product Unit',
    )
    official_batch_no = fields.Char(
        string='Official Batch',
        readonly=True,
    )
    existing_lot_id = fields.Many2one(
        'stock.lot',
        string='Official Lot',
        readonly=True,
        check_company=True,
    )
