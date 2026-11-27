"""Manual corrections of the collection rows -- archive fields only.

A correction states a value that truly exists but was missed or
mis-captured (nameplate numbers, batch numbers, model codes...). The
correction never touches the raw columns: it rides along at synthesis
and is fully audited (who/when/old/new/basis). Measured values and the
conclusion are NOT correctable -- the selection whitelist is the hard
boundary, there is no path that turns a failed measurement into a
passing one.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

# the archive-type columns a correction may target; everything else
# (measurements, conclusion, anchors) is read-only by design
CORRECTABLE_FIELDS = [
    ('model_code', 'Model Code'),
    ('plant_code', 'Plant Code'),
    ('nameplate_code', 'Nameplate Code'),
    ('table_no', 'Table No'),
    ('table_address', 'Table Address'),
    ('asset_management_no', 'Asset Management No'),
    ('software_version', 'Software Version'),
    ('logic_address', 'Logic Address'),
    ('bureau_num', 'Bureau Number'),
]


class EipCleanFix(models.Model):
    _name = 'sn.wsd.eip.clean.fix'
    _description = 'EIP Collection Correction'
    _order = 'source_id, field_name, id'
    _rec_name = 'field_name'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    source_id = fields.Many2one(
        'sn.wsd.eip.pass.record', string='Collection Row', required=True,
        ondelete='cascade', index=True, check_company=True)
    field_name = fields.Selection(
        selection=CORRECTABLE_FIELDS, string='Field', required=True,
        index=True,
        help='Archive-type column the correction supplies; measured '
             'values and the conclusion are never correctable.')
    original_value = fields.Char(
        string='Original Value', readonly=True,
        help='Raw column value when the correction was written (audit).')
    value = fields.Char(
        string='Corrected Value', required=True,
        help='The true value, taken from a real source (issued lists, '
             'paper records, the physical unit).')
    basis = fields.Char(
        string='Basis', required=True,
        help='Where the corrected value comes from; mandatory for the '
             'audit trail.')

    _fix_uniq = models.Constraint(
        'unique(source_id, field_name)',
        'This collection row already has a correction for the field.',
    )

    @api.model
    def _original_of(self, record, field_name):
        value = record[field_name]
        return str(value) if value else ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            record = self.env['sn.wsd.eip.pass.record'].browse(
                vals.get('source_id'))
            if record.state == 'delivered':
                raise UserError(_(
                    'Delivered rows are frozen; corrections are not '
                    'possible.'))
            field_name = vals.get('field_name')
            if field_name not in dict(CORRECTABLE_FIELDS):
                raise UserError(_(
                    'Field %s is not correctable: only archive-type '
                    'fields are.', field_name))
            vals.setdefault('original_value', self._original_of(
                record, field_name))
            # the correction always belongs to the row's company
            vals.setdefault('company_id', record.company_id.id)
        return super().create(vals_list)


class EipCleanFixWizard(models.TransientModel):
    """Batch correction: one true value applied to a whole filtered
    batch of rows (e.g. every rejected parameter-setting row missing
    the nameplate), then an immediate batch re-clean."""

    _name = 'sn.wsd.eip.clean.fix.wizard'
    _description = 'EIP Collection Batch Correction'

    record_ids = fields.Char(
        string='Collection Rows',
        help='Comma-separated ids of the rows the correction applies '
             'to (filled from the ledger selection).')
    field_name = fields.Selection(
        selection=CORRECTABLE_FIELDS, string='Field', required=True)
    value = fields.Char(
        string='Corrected Value', required=True,
        help='The true value, taken from a real source.')
    basis = fields.Char(string='Basis', required=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        ids = self.env.context.get('active_ids') or []
        if ids:
            values.setdefault(
                'record_ids', ','.join(str(record_id) for record_id in ids))
        return values

    def action_apply(self):
        self.ensure_one()
        ids = [
            int(piece) for piece in (self.record_ids or '').split(',')
            if piece.strip().isdigit()]
        rows = self.env['sn.wsd.eip.pass.record'].browse(ids).exists()
        rows = rows.filtered(lambda item: item.state != 'delivered')
        if not rows:
            raise UserError(_('No correctable collection rows selected.'))
        Fix = self.env['sn.wsd.eip.clean.fix']
        for row in rows:
            fix = Fix.search([('source_id', '=', row.id),
                              ('field_name', '=', self.field_name)],
                             limit=1)
            if fix:
                fix.write({'value': self.value, 'basis': self.basis})
            else:
                Fix.create({
                    'source_id': row.id,
                    'field_name': self.field_name,
                    'value': self.value,
                    'basis': self.basis,
                })
        rows._eip_clean_rows()
        return {'type': 'ir.actions.act_window_close'}


class EipCleanOrderWizard(models.TransientModel):
    """The single cleansing trigger: type a work order number, and every
    collection row of that order is (re-)cleansed. No cron, no free
    selection -- re-cleaning is only possible against a work order."""

    _name = 'sn.wsd.eip.clean.order.wizard'
    _description = 'EIP Collection Re-clean by Work Order'

    work_order_no = fields.Char(
        string='Work Order No', required=True,
        help='Every collection row carrying this work order number is '
             're-judged by the gates; qualified rows regenerate their '
             'outbox snapshots, rejected rows keep the fresh reason.')

    def action_re_clean(self):
        self.ensure_one()
        rows = self.env['sn.wsd.eip.pass.record']._eip_clean_by_order(
            self.work_order_no.strip())
        qualified = sum(1 for row in rows if row.state == 'qualified')
        # the result as a toast on the bus; the 'effect' key of the
        # returned action is not handled by the Odoo 19 webclient
        self.env['bus.bus']._sendone(
            self.env.user.partner_id, 'simple_notification', {
                'type': 'success' if qualified else 'warning',
                'title': _('Re-clean by Work Order'),
                'message': _(
                    '%(total)s rows re-cleaned for %(order)s: '
                    '%(qualified)s qualified, %(rejected)s rejected.',
                    total=len(rows),
                    order=self.work_order_no,
                    qualified=qualified,
                    rejected=len(rows) - qualified),
            })
        return {'type': 'ir.actions.act_window_close'}
