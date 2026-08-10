from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MrpSubstituteWizard(models.TransientModel):
    _name = 'mrp.substitute.wizard'
    _description = 'Substitute Material Wizard'

    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        required=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='workorder_id.production_id',
        readonly=True,
    )
    original_product_id = fields.Many2one(
        'product.product',
        string='Original Product',
        required=True,
        domain="[('id', 'in', available_original_product_ids)]",
    )
    available_original_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_available_original_product_ids',
    )
    available_bom_line_ids = fields.Many2many(
        'mrp.bom.line',
        compute='_compute_available_bom_line_ids',
    )
    bom_line_id = fields.Many2one(
        'mrp.bom.line',
        string='BoM Line',
        compute='_compute_bom_line_id',
        store=False,
    )
    scanned_barcode = fields.Char(string='Scanned Barcode')
    scanned_product_id = fields.Many2one(
        'product.product',
        string='Scanned Product',
        compute='_compute_scanned_product',
        store=False,
    )
    substitute_qty = fields.Float(
        string='Substitute Qty',
        required=True,
        default=1.0,
    )
    substitute_lot = fields.Char(string='Substitute Lot/Serial')
    substitute_lot_id = fields.Many2one(
        'stock.lot',
        string='Substitute Lot',
        compute='_compute_substitute_lot_id',
        store=False,
    )
    note = fields.Text(string='Note')

    @api.depends('production_id.bom_id.bom_line_ids.substitute_line_ids')
    def _compute_available_bom_line_ids(self):
        for wizard in self:
            bom = wizard.production_id.bom_id
            wizard.available_bom_line_ids = bom.bom_line_ids.filtered('substitute_line_ids') if bom else False

    @api.depends('available_bom_line_ids')
    def _compute_available_original_product_ids(self):
        for wizard in self:
            wizard.available_original_product_ids = wizard.available_bom_line_ids.product_id

    @api.depends('available_bom_line_ids', 'original_product_id')
    def _compute_bom_line_id(self):
        for wizard in self:
            wizard.bom_line_id = wizard.available_bom_line_ids.filtered(
                lambda line: line.product_id == wizard.original_product_id
            )[:1]

    @api.depends('scanned_barcode')
    def _compute_scanned_product(self):
        product_model = self.env['product.product']
        for wizard in self:
            if wizard.scanned_barcode:
                wizard.scanned_product_id = product_model.search([
                    '|',
                    ('barcode', '=', wizard.scanned_barcode),
                    ('default_code', '=', wizard.scanned_barcode),
                ], limit=1)
            else:
                wizard.scanned_product_id = False

    @api.depends('scanned_product_id', 'substitute_lot')
    def _compute_substitute_lot_id(self):
        lot_model = self.env['stock.lot']
        for wizard in self:
            if wizard.scanned_product_id and wizard.substitute_lot:
                wizard.substitute_lot_id = lot_model.search([
                    ('product_id', '=', wizard.scanned_product_id.id),
                    ('name', '=', wizard.substitute_lot),
                ], limit=1)
            else:
                wizard.substitute_lot_id = False

    def action_validate(self):
        self.ensure_one()
        if not self.scanned_product_id:
            raise UserError(_('The scanned substitute product could not be identified.'))
        if not self.bom_line_id:
            raise UserError(_('No BoM substitute rule exists for the selected original product on this manufacturing order.'))

        substitute_rule = self.bom_line_id.substitute_line_ids.filtered(
            lambda line: line.substitute_product_id == self.scanned_product_id
        )[:1]
        if not substitute_rule:
            raise UserError(_(
                '%(sub)s cannot replace %(org)s. Configure the substitute on the BoM line first.',
                sub=self.scanned_product_id.display_name,
                org=self.original_product_id.display_name,
            ))

        substitute_bom_line = self.production_id.bom_id.bom_line_ids.filtered(
            lambda line: line.product_id == self.scanned_product_id
            and line.x_substitution_origin_line_id == self.bom_line_id
        )[:1]
        matching_move = self.production_id.move_raw_ids.filtered(
            lambda move: move.product_id == self.scanned_product_id and move.state not in ('done', 'cancel')
        )[:1]
        if not substitute_bom_line or not matching_move:
            raise UserError(_(
                'The substitute product is not present on the manufacturing order. Update the production BoM and regenerate the order before recording usage.'
            ))

        usage = self.env['mrp.substitute.usage'].create({
            'production_id': self.production_id.id,
            'workorder_id': self.workorder_id.id,
            'bom_id': self.production_id.bom_id.id,
            'bom_line_id': self.bom_line_id.id,
            'substitute_bom_line_id': substitute_bom_line.id,
            'original_product_id': self.original_product_id.id,
            'substitute_product_id': self.scanned_product_id.id,
            'substitute_lot_id': self.substitute_lot_id.id,
            'original_uom_qty': self.substitute_qty,
            'substitute_uom_qty': self.substitute_qty,
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now(),
            'state': 'approved',
            'note': self.note,
        })
        usage.consume_move_line_id = matching_move.move_line_ids.filtered(
            lambda line: line.state != 'cancel'
        )[:1].id if matching_move.move_line_ids else False

        return {
            'type': 'ir.actions.act_window_close',
            'infos': {'usage_id': usage.id},
        }
