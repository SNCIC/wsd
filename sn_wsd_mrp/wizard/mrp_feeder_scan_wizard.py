from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MrpFeederScanWizard(models.TransientModel):
    _name = 'mrp.feeder.scan.wizard'
    _description = 'Feeder Barcode Verification'

    feeder_line_id = fields.Many2one(
        'mrp.feeder.line',
        string='Feeder Position',
        required=True,
    )
    expected_product_id = fields.Many2one(
        'product.product',
        string='Expected Material',
        related='feeder_line_id.expected_product_id',
        readonly=True,
    )
    scanned_barcode = fields.Char(string='Scanned Material Barcode')
    scanned_product_id = fields.Many2one(
        'product.product',
        string='Identified Material',
        compute='_compute_scanned_product',
        store=False,
    )
    scanned_product_name = fields.Char(
        string='Identified Material Name',
        compute='_compute_scanned_product',
        store=False,
    )
    scanned_lot = fields.Char(string='Scanned Lot Number')
    scanned_lot_id = fields.Many2one(
        'stock.lot',
        string='Identified Lot',
        compute='_compute_scanned_lot',
        store=False,
    )
    match_status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('match', 'Matched'),
            ('mismatch', 'Mismatched'),
        ],
        string='Verification Result',
        default='pending',
        readonly=True,
    )
    message = fields.Char(string='Message', readonly=True)
    loaded_qty = fields.Float(
        string='Loaded Quantity',
        default=1.0,
        required=True,
    )

    @api.depends('scanned_barcode')
    def _compute_scanned_product(self):
        Product = self.env['product.product']
        for wizard in self:
            if wizard.scanned_barcode:
                product = Product.search([
                    '|',
                    ('barcode', '=', wizard.scanned_barcode),
                    ('default_code', '=', wizard.scanned_barcode),
                ], limit=1)
                wizard.scanned_product_id = product
                wizard.scanned_product_name = product.display_name
            else:
                wizard.scanned_product_id = False
                wizard.scanned_product_name = False

    @api.depends('scanned_lot', 'scanned_product_id')
    def _compute_scanned_lot(self):
        Lot = self.env['stock.lot']
        for wizard in self:
            if wizard.scanned_lot and wizard.scanned_product_id:
                wizard.scanned_lot_id = Lot.search([
                    ('product_id', '=', wizard.scanned_product_id.id),
                    ('name', '=', wizard.scanned_lot),
                ], limit=1)
            else:
                wizard.scanned_lot_id = False

    def action_verify(self):
        self.ensure_one()
        if not self.scanned_product_id:
            raise UserError(_('No material was identified. Please check the barcode.'))
        if self.scanned_product_id != self.expected_product_id:
            raise UserError(_(
                'Material mismatch.\nExpected: %(expected)s\nScanned: %(actual)s',
                expected=self.expected_product_id.display_name,
                actual=self.scanned_product_name or self.scanned_barcode,
            ))

        self.feeder_line_id.write({
            'actual_product_id': self.scanned_product_id.id,
            'lot_id': self.scanned_lot_id.id,
            'lot_name': self.scanned_lot,
            'loaded_qty': self.loaded_qty,
            'state': 'verified',
            'verify_datetime': fields.Datetime.now(),
            'verify_user_id': self.env.user.id,
        })
        self.write({
            'match_status': 'match',
            'message': _(
                'Verification passed: %(product)s / Lot: %(lot)s',
                product=self.scanned_product_name,
                lot=self.scanned_lot or _('No Lot'),
            ),
        })
        return {'type': 'ir.actions.act_window_close'}

    def action_verify_and_continue(self):
        self.ensure_one()
        self.action_verify()
        next_line = self.env['mrp.feeder.line'].search([
            ('workorder_id', '=', self.feeder_line_id.workorder_id.id),
            ('state', '=', 'pending'),
        ], order='feeder_no, id', limit=1)
        if next_line:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Feeder Barcode Verification'),
                'res_model': 'mrp.feeder.scan.wizard',
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'new',
                'context': {
                    'default_feeder_line_id': next_line.id,
                },
            }
        return {'type': 'ir.actions.act_window_close'}
