from odoo import _, fields, models
from odoo.exceptions import ValidationError


class MeterPackRecord(models.Model):
    _name = 'sn.wsd.meter.pack.record'
    _description = 'Meter Pack Record'
    _order = 'pack_time desc, id desc'

    active = fields.Boolean(default=True)
    name = fields.Char(
        required=True,
        copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('sn.wsd.meter.pack.record') or 'New',
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN', required=True, index=True,
        check_company=True, ondelete='restrict',
    )
    production_id = fields.Many2one('mrp.production', index=True, check_company=True)
    pack_route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Pack MES Route Operation',
        index=True,
        check_company=True,
    )
    seal_no = fields.Char(index=True)
    carton_no = fields.Char(index=True)
    carton_seq = fields.Integer()
    pallet_no = fields.Char(index=True)
    carton_package_id = fields.Many2one(
        'stock.package', string='Carton Package', index=True, ondelete='restrict', copy=False,
    )
    pallet_package_id = fields.Many2one(
        'stock.package', string='Pallet Package', index=True, ondelete='restrict', copy=False,
    )
    pack_time = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    operator_code = fields.Char(index=True)
    scan_check_result = fields.Selection([('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold')], default='pass')
    note = fields.Char()
    barcode_line_ids = fields.One2many(
        'sn.wsd.meter.pack.barcode', 'pack_id', string='Barcode Lines')

    def _get_serial_lot(self):
        self.ensure_one()
        lot = self.env['stock.lot'].with_context(active_test=False).search([
            ('name', '=', self.serial_identity_id.name),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not lot and self.production_id:
            lot = self.env['stock.lot'].create({
                'name': self.serial_identity_id.name,
                'product_id': self.production_id.product_id.id,
                'company_id': self.company_id.id,
            })
        return lot

    def action_sync_stock_package(self):
        for record in self.filtered(lambda item: item.active and item.carton_package_id):
            production = record.production_id
            lot = record._get_serial_lot()
            if not lot or not production:
                continue
            move_lines = production.move_finished_ids.move_line_ids.filtered(
                lambda line: line.lot_id == lot and line.state not in ('done', 'cancel')
            )
            if move_lines:
                move_lines.write({'result_package_id': record.carton_package_id.id})
            quants = self.env['stock.quant'].search([
                ('lot_id', '=', lot.id),
                ('product_id', '=', production.product_id.id),
                ('quantity', '>', 0),
                ('location_id.usage', 'in', ['internal', 'transit']),
            ])
            conflicting = quants.filtered(
                lambda quant: quant.package_id and quant.package_id != record.carton_package_id
            )
            if conflicting:
                raise ValidationError(_(
                    'Serial number %(serial)s is already stored in package %(package)s.'
                ) % {
                    'serial': record.serial_identity_id.name,
                    'package': conflicting.package_id[:1].display_name,
                })
            quants.filtered(lambda quant: not quant.package_id).write({
                'package_id': record.carton_package_id.id,
            })


class MeterPackBarcodeLine(models.Model):
    """One uploaded packing barcode (seals, RF codes, MAC, module, side
    codes) attached to the pack record."""
    _name = 'sn.wsd.meter.pack.barcode'
    _description = 'Meter Pack Barcode Line'
    _order = 'id'

    pack_id = fields.Many2one(
        'sn.wsd.meter.pack.record', required=True, ondelete='cascade',
        index=True)
    code = fields.Char(required=True, index=True,
                       help='Source field of the uploaded barcode, e.g. M_PACK_MAC.')
    value = fields.Char(required=True)
    company_id = fields.Many2one(related='pack_id.company_id', store=True)
