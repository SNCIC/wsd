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
    serial_id = fields.Many2one('sn.wsd.internal.serial', required=True, index=True, check_company=True)
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

    def action_apply_to_serial(self):
        for record in self.filtered('active'):
            record.serial_id.write({
                'seal_no': record.seal_no,
                'carton_no': record.carton_no,
                'pallet_no': record.pallet_no,
                'pack_date': record.pack_time,
            })
            if record.pack_route_operation_id:
                record.serial_id.current_route_operation_id = record.pack_route_operation_id
            record.action_sync_stock_package()

    def action_sync_stock_package(self):
        for record in self.filtered(lambda item: item.active and item.carton_package_id):
            serial = record.serial_id
            production = record.production_id
            lot = serial.lot_id
            if not lot and production:
                lot = production._get_or_create_stage_lot(serial.serial_no, identity=serial.serial_identity_id)
                serial.lot_id = lot
            if not lot or not production:
                continue
            move_lines = production.move_finished_ids.move_line_ids.filtered(
                lambda line: line.lot_id == lot and line.state not in ('done', 'cancel')
            )
            if move_lines:
                move_lines.write({'result_package_id': record.carton_package_id.id})
            quants = self.env['stock.quant'].search([
                ('lot_id', '=', lot.id),
                ('product_id', '=', serial.product_id.id),
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
                    'serial': serial.serial_no,
                    'package': conflicting.package_id[:1].display_name,
                })
            quants.filtered(lambda quant: not quant.package_id).write({
                'package_id': record.carton_package_id.id,
            })
