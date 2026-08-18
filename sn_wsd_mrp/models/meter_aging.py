from odoo import fields, models


class MeterAgingBatch(models.Model):
    _name = 'sn.wsd.meter.aging.batch'
    _description = 'Meter Aging Batch'
    _order = 'start_time desc, id desc'

    name = fields.Char(
        required=True,
        copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('sn.wsd.meter.aging.batch') or 'New',
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    production_id = fields.Many2one('mrp.production', index=True, check_company=True)
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='MES Route Operation',
        index=True,
        check_company=True,
    )
    equipment_id = fields.Many2one('maintenance.equipment', index=True, check_company=True)
    aging_cart_no = fields.Char(index=True)
    planned_hours = fields.Float(default=8.0)
    actual_hours = fields.Float()
    start_time = fields.Datetime(index=True)
    end_time = fields.Datetime(index=True)
    operator_code = fields.Char(index=True)
    status = fields.Selection(
        [('draft', 'Draft'), ('loaded', 'Loaded'), ('aging', 'Aging'), ('done', 'Done'), ('cancel', 'Cancelled')],
        default='draft',
        required=True,
        index=True,
    )
    line_ids = fields.One2many('sn.wsd.meter.aging.batch.line', 'batch_id', string='Serial Lines')
    line_count = fields.Integer(compute='_compute_line_count')
    note = fields.Text()

    def _compute_line_count(self):
        for batch in self:
            batch.line_count = len(batch.line_ids)

    def action_start(self):
        for batch in self:
            batch.write({
                'status': 'aging',
                'start_time': batch.start_time or fields.Datetime.now(),
            })
            batch.line_ids.filtered(lambda l: l.serial_id).mapped('serial_id').write({'current_aging_batch_id': batch.id})

    def action_finish(self):
        for batch in self:
            end_time = fields.Datetime.now()
            actual_hours = 0.0
            if batch.start_time:
                delta = end_time - batch.start_time
                actual_hours = delta.total_seconds() / 3600.0
            batch.write({
                'status': 'done',
                'end_time': end_time,
                'actual_hours': actual_hours,
            })
            batch.line_ids.filtered(lambda l: l.serial_id).mapped('serial_id').write({
                'aging_result': 'pass', 'current_aging_batch_id': False,
            })
            batch.line_ids.filtered(lambda l: not l.unload_time).write({'unload_time': end_time})


class MeterAgingBatchLine(models.Model):
    _name = 'sn.wsd.meter.aging.batch.line'
    _description = 'Meter Aging Batch Line'
    _order = 'slot_no, id'

    batch_id = fields.Many2one('sn.wsd.meter.aging.batch', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='batch_id.company_id', store=True)
    serial_id = fields.Many2one('sn.wsd.internal.serial', required=True, index=True, check_company=True)
    production_id = fields.Many2one(related='serial_id.production_id', store=True)
    slot_no = fields.Char(required=True, index=True)
    load_time = fields.Datetime(default=fields.Datetime.now)
    unload_time = fields.Datetime()
    result = fields.Selection([('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold')], default='pass')
    exception_code = fields.Char(index=True)
    note = fields.Char()
