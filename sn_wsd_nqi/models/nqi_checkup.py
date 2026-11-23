"""SN data checkup: per-object completeness report across the NQI
mirror tables (read-only aggregation, no locks, indexed serial_no)."""
from odoo import _, fields, models

CHECKUP_TABLES = [
    # (model, domain label)
    ('sn.wsd.nqi.fit.meter.info', 'Asset Info'),
    ('sn.wsd.nqi.fit.meter.mounting', 'Meter Process'),
    ('sn.wsd.nqi.fit.pcb.mounting', 'PCB Process'),
    ('sn.wsd.nqi.fit.pcb.serial.bind', 'PCB Serial Bridge'),
    ('sn.wsd.nqi.mt.mounting', 'Test Summary'),
    ('sn.wsd.nqi.mt.aoi', 'AOI'),
    ('sn.wsd.nqi.mt.single', 'PCB Test'),
    ('sn.wsd.nqi.mt.intuit', 'Appearance'),
    ('sn.wsd.nqi.mt.volt', 'AC Voltage Withstand'),
    ('sn.wsd.nqi.mt.starting', 'Starting'),
    ('sn.wsd.nqi.mt.creeping', 'Creeping'),
    ('sn.wsd.nqi.mt.const', 'Meter Constant'),
    ('sn.wsd.nqi.mt.dayerr', 'Daily Timing Error'),
    ('sn.wsd.nqi.mt.basicerr', 'Basic Error'),
    ('sn.wsd.nqi.mt.ts', 'Time-Switch Error'),
    ('sn.wsd.nqi.mt.function', 'Function Test'),
    ('sn.wsd.nqi.mt.rfid', 'RFID'),
    ('sn.wsd.nqi.mt.time.error', 'Clock Error'),
    ('sn.wsd.nqi.tt.standard', 'Protocol Consistency'),
    ('sn.wsd.nqi.tt.error', 'Error Variation'),
    ('sn.wsd.nqi.tt.consist', 'Error Consistency'),
    ('sn.wsd.nqi.ot.other', 'Other Tests'),
]


class NqiCheckupLine(models.TransientModel):
    _name = 'sn.wsd.nqi.checkup.line'
    _description = 'NQI Checkup Line'
    _order = 'sequence, id'

    checkup_id = fields.Many2one(
        'sn.wsd.nqi.checkup', string='Checkup', required=True,
        ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    table_label = fields.Char(string='Data Domain')
    row_count = fields.Integer(string='Rows', default=0)
    state = fields.Selection(
        [('ok', 'Complete'), ('warn', 'Missing Columns'),
         ('none', 'No Rows')],
        string='Status', default='none')
    missing_note = fields.Char(string='Missing')


class NqiCheckup(models.TransientModel):
    _name = 'sn.wsd.nqi.checkup'
    _description = 'NQI SN Checkup'

    sn = fields.Char(string='SN', required=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Done')], default='draft')
    line_ids = fields.One2many(
        'sn.wsd.nqi.checkup.line', 'checkup_id', string='Domains')
    summary = fields.Char(string='Summary', readonly=True)

    def action_run(self):
        for checkup in self:
            checkup.line_ids.unlink()
            lines = []
            for sequence, (model_name, label) in enumerate(
                    CHECKUP_TABLES, start=10):
                model = self.env[model_name].sudo()
                base = [('company_id', 'in', self.env.companies.ids)]
                key_clauses = [
                    (field, '=', checkup.sn)
                    for field in ('serial_no', 'pcb_code')
                    if field in model._fields]
                if len(key_clauses) == 1:
                    domain = base + key_clauses
                elif key_clauses:
                    domain = base + ['|'] + key_clauses
                else:
                    continue
                rows = model.search_count(domain)
                incomplete = model.search_count(
                    domain + [('missing_count', '>', 0)])
                state = 'none' if not rows else (
                    'warn' if incomplete else 'ok')
                lines.append((0, 0, {
                    'sequence': sequence,
                    'table_label': label,
                    'row_count': rows,
                    'state': state,
                    'missing_note': (
                        _('%d rows missing columns') % incomplete
                        if incomplete else ''),
                }))
            checkup.write({
                'line_ids': lines,
                'state': 'done',
                'summary': _('Checkup for %s') % checkup.sn,
            })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.wsd.nqi.checkup',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
