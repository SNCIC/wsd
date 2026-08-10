import math
import re

from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


class LotReelSplitWizard(models.TransientModel):
    _name = 'sn.lot.reel.split.wizard'
    _description = 'Generate Reel Lots'
    _check_company_auto = True

    picking_id = fields.Many2one('stock.picking', string='Storage Transfer', required=True, readonly=True, check_company=True)
    source_move_id = fields.Many2one(
        'stock.move', string='Product Move', required=True, check_company=True,
        domain="[('picking_id', '=', picking_id), ('product_id.tracking', '=', 'lot'), ('state', 'not in', ('done', 'cancel'))]",
    )
    product_id = fields.Many2one(related='source_move_id.product_id', readonly=True)
    product_uom_id = fields.Many2one(related='product_id.uom_id', readonly=True)
    source_lot_id = fields.Many2one(
        'stock.lot', string='Source Lot', required=True, check_company=True,
        domain="[('product_id', '=', product_id), ('id', 'in', available_source_lot_ids)]",
    )
    available_source_lot_ids = fields.Many2many('stock.lot', compute='_compute_available_source_lot_ids')
    split_quantity = fields.Float(string='Quantity to Split', required=True, digits='Product Unit')
    quantity_per_reel = fields.Float(string='Quantity per Reel', required=True, digits='Product Unit')
    lot_prefix = fields.Char(string='Reel Lot Prefix', required=True)
    sequence_start = fields.Integer(string='Starting Sequence', required=True, default=1)
    sequence_padding = fields.Integer(string='Sequence Digits', required=True, default=3)
    default_location_dest_id = fields.Many2one(
        'stock.location', string='Default Destination', required=True, check_company=True,
        domain="[('id', 'child_of', picking_id.location_dest_id), ('usage', '=', 'internal')]",
    )
    picking_location_dest_id = fields.Many2one(related='picking_id.location_dest_id', string='Storage Destination')
    line_ids = fields.One2many('sn.lot.reel.split.wizard.line', 'wizard_id', string='Reel Lots')
    company_id = fields.Many2one(related='picking_id.company_id', readonly=True)

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        picking = self.env['stock.picking'].browse(values.get('picking_id')).exists()
        if not picking:
            return values
        eligible_moves = picking.move_ids.filtered(
            lambda move: move.state not in ('done', 'cancel') and move.product_id.tracking == 'lot'
        )
        if len(eligible_moves) == 1:
            values['source_move_id'] = eligible_moves.id
        values['default_location_dest_id'] = picking.location_dest_id.id
        return values

    @api.depends('source_move_id', 'source_move_id.move_line_ids.lot_id')
    def _compute_available_source_lot_ids(self):
        for wizard in self:
            wizard.available_source_lot_ids = wizard.source_move_id.move_line_ids.filtered(
                lambda line: line.quantity > 0 and line.lot_id
            ).lot_id

    @api.onchange('source_move_id')
    def _onchange_source_move_id(self):
        self.source_lot_id = False
        self.split_quantity = 0
        self.lot_prefix = False
        self.line_ids = [Command.clear()]
        if len(self.available_source_lot_ids) == 1:
            self.source_lot_id = self.available_source_lot_ids
            self._set_source_lot_defaults()

    @api.onchange('source_lot_id')
    def _onchange_source_lot_id(self):
        self.line_ids = [Command.clear()]
        self._set_source_lot_defaults()

    def _set_source_lot_defaults(self):
        """Load the quantity reserved for the selected product and source lot."""
        self.ensure_one()
        if not self.source_lot_id:
            self.split_quantity = 0
            self.lot_prefix = False
            return
        source_lot = self.source_lot_id._origin
        source_lines = self.source_move_id.move_line_ids.filtered(
            lambda line: line.lot_id == source_lot and line.quantity > 0
        )
        self.split_quantity = sum(source_lines.mapped('quantity_product_uom'))
        self.lot_prefix = f'{source_lot.name}-'
        self.sequence_start = self._get_next_sequence()

    def _get_next_sequence(self):
        self.ensure_one()
        if not self.source_lot_id:
            return 1
        return max(self.source_lot_id.child_lot_ids.mapped('reel_sequence'), default=0) + 1

    def action_generate_lines(self):
        self.ensure_one()
        self._validate_header()
        quantities = self._get_reel_quantities()
        commands = [Command.clear()]
        for offset, quantity in enumerate(quantities):
            sequence = self.sequence_start + offset
            commands.append(Command.create({
                'sequence': sequence,
                'lot_name': f'{self.lot_prefix}{sequence:0{self.sequence_padding}d}',
                'quantity': quantity,
                'location_dest_id': self.default_location_dest_id.id,
                'is_remainder': self.product_uom_id.compare(quantity, self.quantity_per_reel) < 0,
            }))
        self.line_ids = commands
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Reel Lots'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def _validate_header(self):
        self.ensure_one()
        if not self.picking_id.can_generate_reel_lots:
            raise UserError(_('This transfer is not an active receipt storage transfer.'))
        warehouse = self.env['stock.warehouse'].search([
            ('store_type_id', '=', self.picking_id.picking_type_id.id),
            ('company_id', '=', self.company_id.id),
            ('reception_steps', 'in', ('two_steps', 'three_steps')),
        ], limit=1)
        if not warehouse:
            raise UserError(_('The transfer operation type is not configured as a receipt storage step.'))
        if self.source_move_id.picking_id != self.picking_id:
            raise ValidationError(_('The selected product move does not belong to this storage transfer.'))
        if self.product_id.tracking != 'lot':
            raise ValidationError(_('Only products tracked by lots can be split into reel lots.'))
        if self.source_lot_id not in self.available_source_lot_ids:
            raise ValidationError(_('The source lot is not reserved on the selected product move.'))
        if self.split_quantity <= 0 or self.quantity_per_reel <= 0:
            raise ValidationError(_('Split quantity and quantity per reel must be greater than zero.'))
        if self.sequence_start <= 0 or self.sequence_padding <= 0 or self.sequence_padding > 9:
            raise ValidationError(_('The sequence start must be positive and sequence digits must be between 1 and 9.'))
        if not self.lot_prefix or not self.lot_prefix.startswith(f'{self.source_lot_id.name}-'):
            raise ValidationError(_('The reel lot prefix must start with the complete source lot followed by a hyphen.'))
        if self.default_location_dest_id.usage != 'internal' or not self.default_location_dest_id._child_of(self.picking_id.location_dest_id):
            raise ValidationError(_('The destination must be an internal location below the transfer destination.'))
        source_lines = self.source_move_id.move_line_ids.filtered(
            lambda line: line.lot_id == self.source_lot_id and line.quantity > 0
        )
        if self.source_move_id.picked or any(source_lines.mapped('picked')):
            raise ValidationError(_('Clear the Picked status before generating reel lots.'))
        if source_lines.package_id or source_lines.result_package_id or source_lines.owner_id:
            raise ValidationError(_('Reel lot generation does not support packaged or owner-restricted source stock. Unpack it first.'))
        reserved_quantity = sum(source_lines.mapped('quantity_product_uom'))
        if self.product_uom_id.compare(self.split_quantity, reserved_quantity) != 0:
            raise ValidationError(_(
                'The split quantity must equal the quantity reserved from source lot %(lot)s: %(quantity)s %(uom)s.',
                lot=self.source_lot_id.display_name,
                quantity=reserved_quantity,
                uom=self.product_uom_id.display_name,
            ))

    def _get_reel_quantities(self):
        self.ensure_one()
        full_reel_count = int(math.floor(self.split_quantity / self.quantity_per_reel))
        quantities = [self.quantity_per_reel] * full_reel_count
        remainder = self.split_quantity - (self.quantity_per_reel * full_reel_count)
        if not float_is_zero(remainder, precision_rounding=self.product_uom_id.rounding):
            quantities.append(remainder)
        if not quantities:
            quantities.append(self.split_quantity)
        return quantities

    def action_apply(self):
        self.ensure_one()
        self._validate_header()
        if not self.line_ids:
            raise ValidationError(_('Generate the reel lot lines before applying the split.'))
        if self.product_uom_id.compare(sum(self.line_ids.mapped('quantity')), self.split_quantity) != 0:
            raise ValidationError(_('The sum of reel quantities must equal the split quantity.'))
        if any(line.quantity <= 0 for line in self.line_ids):
            raise ValidationError(_('Every reel quantity must be greater than zero.'))
        if any(
            line.location_dest_id.usage != 'internal'
            or not line.location_dest_id._child_of(self.picking_id.location_dest_id)
            for line in self.line_ids
        ):
            raise ValidationError(_('Every reel destination must be an internal location below the transfer destination.'))
        if len(set(self.line_ids.mapped('lot_name'))) != len(self.line_ids):
            raise ValidationError(_('Reel lot names must be unique.'))

        self.env.cr.execute('SELECT id FROM stock_lot WHERE id = %s FOR UPDATE', [self.source_lot_id.id])
        expected_start = self._get_next_sequence()
        if self.sequence_start < expected_start:
            raise ValidationError(_(
                'The starting sequence is no longer available. Regenerate the lines starting from %(sequence)s.',
                sequence=expected_start,
            ))
        existing_lots = self.env['stock.lot'].search([
            ('product_id', '=', self.product_id.id),
            ('name', 'in', self.line_ids.mapped('lot_name')),
            '|', ('company_id', '=', self.company_id.id), ('company_id', '=', False),
        ])
        if existing_lots:
            raise ValidationError(_('The following reel lot names already exist: %s', ', '.join(existing_lots.mapped('name'))))

        source_lines = self.source_move_id.move_line_ids.filtered(
            lambda line: line.lot_id == self.source_lot_id and line.quantity > 0
        )
        preserved_lines = self.source_move_id.move_line_ids.filtered(lambda line: line.quantity > 0) - source_lines
        preserved_values = self._prepare_preserved_line_values(preserved_lines)
        self.source_move_id._do_unreserve()
        available_quantity = self.env['stock.quant']._get_available_quantity(
            self.product_id, self.source_move_id.location_id, lot_id=self.source_lot_id, strict=True,
        )
        if self.product_uom_id.compare(available_quantity, self.split_quantity) < 0:
            raise ValidationError(_(
                'Source lot %(lot)s has only %(quantity)s %(uom)s available in %(location)s.',
                lot=self.source_lot_id.display_name,
                quantity=available_quantity,
                uom=self.product_uom_id.display_name,
                location=self.source_move_id.location_id.display_name,
            ))

        split = self.env['sn.lot.reel.split'].create({
            'name': self.env['ir.sequence'].next_by_code('sn.lot.reel.split') or '/',
            'picking_id': self.picking_id.id,
            'source_move_id': self.source_move_id.id,
            'product_id': self.product_id.id,
            'source_lot_id': self.source_lot_id.id,
            'source_location_id': self.source_move_id.location_id.id,
            'quantity': self.split_quantity,
            'quantity_per_reel': self.quantity_per_reel,
            'product_uom_id': self.product_uom_id.id,
            'company_id': self.company_id.id,
        })
        reel_lots = self._create_reel_lots()
        sorted_lines = self.line_ids.sorted('sequence')
        split_lines = self.env['sn.lot.reel.split.line'].create([{
            'split_id': split.id,
            'sequence': wizard_line.sequence,
            'lot_id': reel_lot.id,
            'quantity': wizard_line.quantity,
            'location_dest_id': wizard_line.location_dest_id.id,
            'is_remainder': wizard_line.is_remainder,
        } for wizard_line, reel_lot in zip(sorted_lines, reel_lots)])
        for reel_lot, split_line in zip(reel_lots, split_lines):
            reel_lot.reel_split_line_id = split_line.id

        self._convert_source_lot(split, reel_lots)
        self.env['stock.move.line'].create(
            preserved_values + self._prepare_reel_storage_line_values(reel_lots)
        )
        self.source_move_id._recompute_state()
        self.picking_id.message_post(body=_(
            'Generated %(count)s reel lots from source lot %(lot)s.',
            count=len(reel_lots),
            lot=self.source_lot_id.display_name,
        ))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reel Split'),
            'res_model': 'sn.lot.reel.split',
            'view_mode': 'form',
            'res_id': split.id,
        }

    def _create_reel_lots(self):
        self.ensure_one()
        lots = self.env['stock.lot']
        for line in self.line_ids.sorted('sequence'):
            values = {
                'name': line.lot_name,
                'parent_lot_id': self.source_lot_id.id,
                'reel_sequence': line.sequence,
                'is_reel_lot': True,
                'reel_split_line_id': False,
            }
            if 'standard_price' in self.env['stock.lot']._fields:
                values['standard_price'] = self.source_lot_id.standard_price
            lots |= self.source_lot_id.copy(values)
        return lots

    def _prepare_preserved_line_values(self, lines):
        return [{
            'move_id': line.move_id.id,
            'picking_id': line.picking_id.id,
            'company_id': line.company_id.id,
            'product_id': line.product_id.id,
            'product_uom_id': line.product_uom_id.id,
            'quantity': line.quantity,
            'picked': line.picked,
            'lot_id': line.lot_id.id,
            'location_id': line.location_id.id,
            'location_dest_id': line.location_dest_id.id,
            'package_id': line.package_id.id,
            'result_package_id': line.result_package_id.id,
            'owner_id': line.owner_id.id,
        } for line in lines]

    def _prepare_reel_storage_line_values(self, reel_lots):
        return [{
            'move_id': self.source_move_id.id,
            'picking_id': self.picking_id.id,
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_uom_id.id,
            'quantity': wizard_line.quantity,
            'picked': False,
            'lot_id': reel_lot.id,
            'location_id': self.source_move_id.location_id.id,
            'location_dest_id': wizard_line.location_dest_id.id,
        } for wizard_line, reel_lot in zip(self.line_ids.sorted('sequence'), reel_lots)]

    def _convert_source_lot(self, split, reel_lots):
        production_location = self.product_id.with_company(
            self.company_id
        ).property_stock_production
        if not production_location:
            self.company_id.create_missing_production_location()
            production_location = self.product_id.with_company(
                self.company_id
            ).property_stock_production
        common_values = {
            'product_id': self.product_id.id,
            'product_uom': self.product_uom_id.id,
            'company_id': self.company_id.id,
            'origin': split.name,
            'reel_split_id': split.id,
            'picking_type_id': self.picking_id.picking_type_id.id,
        }
        consume_move = self.env['stock.move'].create({
            **common_values,
            'product_uom_qty': self.split_quantity,
            'location_id': self.source_move_id.location_id.id,
            'location_dest_id': production_location.id,
            'reel_split_role': 'consume',
        })
        produce_moves = self.env['stock.move'].create([{
            **common_values,
            'product_uom_qty': wizard_line.quantity,
            'location_id': production_location.id,
            'location_dest_id': self.source_move_id.location_id.id,
            'reel_split_role': 'produce',
        } for wizard_line, reel_lot in zip(self.line_ids.sorted('sequence'), reel_lots)])
        consume_move._action_confirm(merge=False)
        produce_moves._action_confirm(merge=False)
        consume_line = self.env['stock.move.line'].create({
            'move_id': consume_move.id,
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_uom_id.id,
            'quantity': self.split_quantity,
            'picked': True,
            'lot_id': self.source_lot_id.id,
            'location_id': self.source_move_id.location_id.id,
            'location_dest_id': production_location.id,
        })
        consume_move._action_done(cancel_backorder=True)
        produce_lines = self.env['stock.move.line'].create([{
            'move_id': produce_move.id,
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_uom_id.id,
            'quantity': wizard_line.quantity,
            'picked': True,
            'lot_id': reel_lot.id,
            'location_id': production_location.id,
            'location_dest_id': self.source_move_id.location_id.id,
        } for wizard_line, reel_lot, produce_move in zip(self.line_ids.sorted('sequence'), reel_lots, produce_moves)])
        produce_moves._action_done(cancel_backorder=True)
        consume_line.produce_line_ids = [Command.set(produce_lines.ids)]


class LotReelSplitWizardLine(models.TransientModel):
    _name = 'sn.lot.reel.split.wizard.line'
    _description = 'Generate Reel Lot Line'
    _order = 'sequence, id'
    _check_company_auto = True

    wizard_id = fields.Many2one('sn.lot.reel.split.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', required=True)
    lot_name = fields.Char(string='Reel Lot', required=True)
    quantity = fields.Float(string='Quantity', required=True, digits='Product Unit')
    location_dest_id = fields.Many2one(
        'stock.location', string='Destination Location', required=True, check_company=True,
        domain="[('id', 'child_of', parent.picking_location_dest_id), ('usage', '=', 'internal')]",
    )
    is_remainder = fields.Boolean(string='Remainder Reel', readonly=True)
    company_id = fields.Many2one(related='wizard_id.company_id')

    @api.constrains('lot_name')
    def _check_lot_name(self):
        for line in self:
            if line.lot_name and not re.match(r'^.+-\d+$', line.lot_name):
                raise ValidationError(_('A reel lot name must end with a hyphen followed by digits.'))
