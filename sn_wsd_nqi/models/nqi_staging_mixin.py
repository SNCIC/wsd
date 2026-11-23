import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class NqiStagingMixin(models.AbstractModel):
    """Envelope shared by every NQI mirror model (V2.1 data model).

    Concrete mirror models declare their NQI columns as plain Char fields
    named after the NQI column (lower snake case) and list the NQI-side
    required column names in ``NQI_REQUIRED``. The mixin carries the
    envelope columns all NQI tables share (enterprise code, write/handle/
    notice/data source), the push state machine, and the completeness
    bookkeeping.

    ``missing_fields`` / ``missing_count`` are stored columns maintained
    by create/write hooks instead of a compute: the required list is
    per-model, so a static ``api.depends`` cannot express the triggers.
    """
    _name = 'sn.wsd.nqi.staging.mixin'
    _description = 'NQI Staging Envelope'
    _order = 'id desc'

    NQI_REQUIRED = ()

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    enterprise_code = fields.Char(
        string='Enterprise Code', index=True, copy=True,
        compute='_compute_enterprise_code', store=True, readonly=False,
        help='NQI ENTERPRISE_CODE. Defaults from the company NQI config; '
             'overridable per row.')
    nqi_write_date = fields.Char(string='NQI Write Date')
    handle_flag = fields.Char(string='Handle Flag')
    handle_date = fields.Char(string='Handle Date')
    notice_no = fields.Char(string='Notice No')
    data_source = fields.Char(
        string='Data Source', size=10,
        help='Aging terminal identifier column, kept for completeness '
             '(aging tests are out of scope).')
    push_state = fields.Selection(
        [('draft', 'Draft'), ('to_push', 'To Push'), ('pushing', 'Pushing'),
         ('pushed', 'Pushed'), ('failed', 'Failed')],
        string='Push State', required=True, default='draft', index=True,
        copy=False)
    missing_fields = fields.Json(
        string='Missing Fields', copy=False,
        help='Names of the NQI required columns still empty on this row. '
             'NULL/False means nothing is missing (the JSON column type '
             'cannot store an empty list).')
    missing_count = fields.Integer(
        string='Missing Count', default=0, copy=False, index=True)

    @api.depends('company_id')
    def _compute_enterprise_code(self):
        config_model = self.env['sn.wsd.nqi.config'].sudo()
        for record in self:
            config = config_model.search(
                [('company_id', '=', record.company_id.id)], limit=1)
            record.enterprise_code = config.enterprise_code

    # ----- completeness bookkeeping -------------------------------------

    def _nqi_missing_columns(self):
        """Names of the declared NQI required columns still falsy."""
        self.ensure_one()
        return [name for name in self.NQI_REQUIRED if not self[name]]

    def _refresh_missing(self):
        """Sync the stored missing bookkeeping on this recordset.

        Writes bypass the public ``write`` (hook would no-op anyway: the
        bookkeeping columns are not in NQI_REQUIRED).
        """
        for record in self:
            missing = record._nqi_missing_columns()
            if (missing != (record.missing_fields or [])
                    or record.missing_count != len(missing)):
                super(NqiStagingMixin, record).write({
                    'missing_fields': missing,
                    'missing_count': len(missing),
                })
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._refresh_missing()
        return records

    def write(self, vals):
        result = super().write(vals)
        if set(self.NQI_REQUIRED) & set(vals):
            self._refresh_missing()
        return result

    # ----- push gate ----------------------------------------------------

    def _nqi_backfill_enterprise_code(self):
        """Heal rows created before the NQI config existed.

        The stored compute only runs at create/when the company changes,
        so rows born earlier keep an empty enterprise code: fill it from
        the config before the gate rejects them.
        """
        config_model = self.env['sn.wsd.nqi.config'].sudo()
        for record in self.filtered(lambda r: not r.enterprise_code):
            config = config_model.search(
                [('company_id', '=', record.company_id.id)], limit=1)
            if config.enterprise_code:
                record.write({'enterprise_code': config.enterprise_code})

    def action_mark_to_push(self):
        """Move draft rows to ``to_push`` after the completeness gate.

        Gate: no missing NQI required columns, and the company NQI config
        exists (it carries the required enterprise code).
        """
        self._refresh_missing()
        self._nqi_backfill_enterprise_code()
        for record in self:
            if record.push_state != 'draft':
                raise UserError(_(
                    'Only draft rows can be marked as to push.'))
            if record.missing_count:
                raise UserError(_(
                    'Row is still missing required columns: %s',
                    ', '.join(record.missing_fields or [])))
            if not record.enterprise_code:
                raise UserError(_(
                    'Company %s has no NQI integration config '
                    '(enterprise code missing).',
                    record.company_id.display_name))
        self.write({'push_state': 'to_push'})
